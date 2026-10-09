"""Read-only Plex data extraction, conservative metadata diagnosis and provider lookup."""
from __future__ import annotations
import csv, io, os, re, sqlite3, json, urllib.request, urllib.parse, urllib.error, time, datetime
from difflib import SequenceMatcher
from pathlib import Path
from functools import lru_cache

DB_DEFAULT = '/var/lib/plexmediaserver/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db'
RELEASE = re.compile(r'(?i)(?:\b(?:BluRay|BRRip|WEB[- .]?DL|WEBRip|DVDRip|x26[45]|H\.?26[45]|HEVC|HDR10?|DV|AAC|DTS|AC3|DD[+.]?5[.]?1|10bit|RARBG|YIFY|1080p|720p|2160p|REPACK|PROPER)\b)')
EPISODE = re.compile(r'(?i)[Ss](\d{1,2})[ ._-]*[Ee](\d{1,3})')
YEAR = re.compile(r'\b(?:19\d{2}|20\d{2})\b')


def clean_name(name: str) -> str:
    name = re.sub(r'(?i)\.(?:mkv|mp4|avi|m4v|wmv|ts)$', '', name)
    name = re.sub(r'(?i)\b(?:19\d{2}|20\d{2})\b.*$', '', name) if RELEASE.search(name) else re.sub(r'\s*\((?:19\d{2}|20\d{2})\).*$', '', name)
    name = RELEASE.split(name)[0]
    name = re.sub(r'[._]+', ' ', name)
    name = re.sub(r'\s*[-–]\s*$', '', name)
    return re.sub(r'\s+', ' ', name).strip(' -_')


def file_title(item):
    path = item.get('file_path') or ''
    if not path: return ''
    filename = Path(path).stem
    if item.get('type') == 'Episode':
        match = EPISODE.search(filename)
        if not match: return ''
        return clean_name(filename[match.end():].lstrip(' -._'))
    return clean_name(Path(path).parent.name) or clean_name(filename)


def norm(s):
    s = re.sub(r'(?i)\b(?:the|a|an)\b', ' ', s or '')
    return re.sub(r'[^a-z0-9]', '', s.lower())


def similar(a, b):
    return SequenceMatcher(None, norm(a), norm(b)).ratio() if norm(a) and norm(b) else 0.0


def filename_proposal(item, proposed_title, year=None, force=False):
    """Suggest same-directory basename for a movie or episode.

    With force=True, produce a filename from the user's staged title/year even
    when the old filename is tidy. This is a proposal, not a write operation.
    """
    if not item.get('file_path') or not proposed_title: return ''
    p = Path(item['file_path']); basename = p.stem
    # These characters are path separators or problematic in media filenames.
    clean_title = re.sub(r'[\\/\x00-\x1f<>"|?*]+', ' - ', proposed_title).strip(' .-')
    if not clean_title: return ''
    if item.get('type') == 'Episode':
        se = EPISODE.search(basename)
        if not se: return ''
        prefix = item.get('series_title') or p.parent.parent.name
        target = f'{prefix} - S{int(se.group(1)):02d}E{int(se.group(2)):02d} - {clean_title}{p.suffix}'
    elif item.get('type') == 'Movie':
        desired_year = str(year if year not in (None, '') else item.get('year') or '')
        target = f'{clean_title}{f" ({desired_year})" if desired_year else ""}{p.suffix}'
    else: return ''
    if target == p.name: return ''
    if not force and basename and not RELEASE.search(basename) and similar(clean_name(basename), proposed_title) >= .84:
        # A correct title with an incorrect release year is still a problem.
        desired_year = str(year if year not in (None, '') else item.get('year') or '')
        named_years = YEAR.findall(basename)
        if not desired_year or not named_years or desired_year == named_years[-1]:
            return ''
    return target


def safe_media_basename(title):
    return re.sub(r'[\\/\x00-\x1f<>"|?*]+', ' - ', title or '').strip(' .-')


def folder_proposal(item, title=None, year=None):
    """Name only; never change paths without separate live preflight/approval."""
    if item.get('type') not in ('Movie', 'Show') or not (item.get('folder_path') or item.get('file_path')):
        return ''
    title = safe_media_basename(title or item.get('plex_title', ''))
    if not title:
        return ''
    selected_year = str(year if year not in (None, '') else item.get('year') or '')
    if selected_year and not re.fullmatch(r'\d{4}', selected_year):
        return ''
    candidate = title + (f' ({selected_year})' if selected_year else '')
    directory = Path(item.get('folder_path') or item['file_path']).parent if not item.get('folder_path') else Path(item['folder_path'])
    return candidate if directory.name != candidate else ''


def derive_show_folders(items):
    """Use episode parentage from Plex SQL, never fuzzy title matching, to locate series folders."""
    groups = {}
    for item in items:
        if item.get('type') != 'Episode' or not item.get('series_id') or not item.get('file_path'):
            continue
        path = Path(item['file_path'])
        parent = path.parent
        if re.fullmatch(r'(?i)(?:season[ ._-]*\d{1,3}|specials|season[ ._-]*specials)', parent.name):
            parent = parent.parent
        groups.setdefault(str(item['series_id']), set()).add(str(parent))
    for item in items:
        if item.get('type') == 'Show' and item.get('series_id'):
            paths = groups.get(str(item['series_id']), set())
            if len(paths) == 1:
                candidate = next(iter(paths))
                # A single episode in an unrecognized season folder could give
                # us that *season* folder, not the series root. Require a
                # recognizable relationship to the show name before offering
                # the whole-series rename action.
                folder_title = Path(candidate).name
                title = item.get('plex_title') or ''
                if (title and folder_title and
                    (similar(folder_title, title) >= .62 or
                     (len(norm(folder_title)) >= 6 and norm(folder_title) in norm(title)) or
                     (len(norm(title)) >= 6 and norm(title) in norm(folder_title)))):
                    item['folder_path'] = candidate
    return items


def year_evidence(item):
    """Extract release-year hints, keeping conflicting folder/file clues distinct.

    These are *file naming conventions*, not proof of theatrical release dates.
    Batch staging requires independent agreement between filename and parent folder.
    """
    result = {'folder_year': '', 'filename_year': '', 'proposed_year': '',
              'batch_safe': False, 'explanation': ''}
    if item.get('type') != 'Movie' or not item.get('file_path'):
        return result
    path = Path(item['file_path'])
    def last_year(name):
        years = [x for x in YEAR.findall(name) if 1888 <= int(x) <= datetime.date.today().year + 1]
        return years[-1] if years else ''
    folder = last_year(path.parent.name)
    filename = last_year(path.stem)
    result['folder_year'], result['filename_year'] = folder, filename
    plex = str(item.get('year') or '')
    if folder and filename and folder != filename:
        result['explanation'] = f'Conflicting naming clues: folder {folder}, filename {filename}. Verify against a provider.'
        return result
    hint = filename or folder
    if not hint or hint == plex:
        return result
    result['proposed_year'] = hint
    # A matching filename and folder is useful, but does not prove original release year.
    # Do not bulk-stage a year if the title suggests a mismatched movie.
    title = item.get('plex_title', '')
    fname = file_title(item)
    title_agrees = bool(title and fname and (
        norm(fname) in norm(title) or norm(title) in norm(fname) or similar(fname, title) >= .7
    ))
    result['batch_safe'] = bool(folder and filename and folder == filename and title_agrees and item.get('guid'))
    result['explanation'] = (f'Folder and filename both say {hint}; confirm the actual release year.'
                             if folder and filename else
                             f'{"Filename" if filename else "Folder"} says {hint}; verify the release year before approving.')
    return result


def diagnose(item):
    title = item.get('plex_title', '').strip(); fname = file_title(item)
    issues = []; new = ''; confidence = 'review'; clues = []
    path = item.get('file_path') or ''
    if item['type'] == 'Episode':
        if not title or title.lower() in ('episode', 'untitled', 'tba') or re.fullmatch(r'(?i)episode\s*\d+',title):
            issues.append('Missing episode title')
            if fname and len(fname) > 2 and not fname.lower().startswith(item.get('series_title','').lower()):
                new = fname; confidence='medium'; clues.append('Filename contains episode name; verify episode order')
        ep = EPISODE.search(Path(path).name) if path else None
        if ep and item.get('season_number') not in (None,'') and item.get('episode_number') not in (None,''):
            if int(ep[1]) != int(item['season_number']) or int(ep[2]) != int(item['episode_number']): issues.append('File episode number differs from Plex')
        if title and fname and len(fname)>3 and not norm(fname) in norm(title) and not norm(title) in norm(fname) and similar(fname,title)<.52:
            issues.append('Episode title differs from filename'); clues.append('Check aired vs DVD order before renaming')
    elif item['type']=='Movie':
        if not title or RELEASE.search(title) or ('...' in title):
            issues.append('Release tags or missing movie title')
            if fname and not RELEASE.search(fname): new=fname; confidence='medium'; clues.append('Recovered from parent directory')
        if fname and title and not (norm(fname) in norm(title) or norm(title) in norm(fname)) and similar(fname,title)<.55:
            issues.append('Movie title differs from library folder'); clues.append('Could be an alternate title or mismatched agent')
        evidence = year_evidence(item)
        if evidence['folder_year'] and evidence['filename_year'] and evidence['folder_year'] != evidence['filename_year']:
            issues.append('Folder and filename years conflict')
            clues.append(evidence['explanation'])
        elif evidence['proposed_year']:
            issues.append('Release year differs from media naming')
            clues.append(evidence['explanation'])
    else:
        if not title: issues.append('Missing show title')
    if path and RELEASE.search(Path(path).stem) and item['type'] in ('Movie','Episode'):
        issues.append('Release/codec tags in filename')
    if not item.get('guid'): issues.append('Unmatched / missing provider GUID')
    if item['type'] in ('Movie', 'Show') and item.get('poster_override','').startswith('media://'): issues.append('Poster is a video frame (review)')
    # Never suggest rewriting an intentional collection/franchise-prefixed title.
    if new and title and norm(new) in norm(title) and len(norm(title)) > len(norm(new)):
        new=''; confidence='review'
    rename = filename_proposal(item, title) if title and path and RELEASE.search(Path(path).stem) else ''
    return {'issues': issues, 'proposed_title': new, 'confidence':confidence if new else 'review', 'clues':clues, 'filename_clue':fname,
            'proposed_filename': rename, 'poster_candidate':'', 'year_evidence':year_evidence(item)}


def normal_item(row):
    item = {key: (str(value or '') if value is not None else '') for key,value in row.items()}
    # Accept export files with either original or standardized keys.
    item['plex_id'] = str(item.get('plex_id') or item.get('id') or '').strip()
    item['type'] = (item.get('type') or '').strip().replace('TV Show', 'Show')
    item['plex_title'] = item.get('plex_title') or item.get('title') or ''
    item['file_path'] = item.get('file_path') or ''
    item['year'] = item.get('year') or ''
    item['series_title'] = item.get('series_title') or ''
    item['poster_override'] = item.get('poster_override') or ''
    item['collections'] = item.get('collections') or ''
    item['guid'] = item.get('guid') or ''
    item['folder_path'] = item.get('folder_path') or ''
    item['series_id'] = str(item.get('series_id') or '')
    return item


def import_csv(csv_text):
    if len(csv_text)>25_000_000: raise ValueError('CSV is too large (25MB max)')
    rows=list(csv.DictReader(io.StringIO(csv_text.lstrip('\ufeff'))))
    if not rows or not {'plex_id','plex_title','type'} <= rows[0].keys():
        raise ValueError('Expected CSV columns: plex_id, plex_title, type, file_path, guid')
    return derive_show_folders(list({r['plex_id']:normal_item(r) for r in rows if r.get('plex_id')}.values()))


def import_db(db_path):
    path=Path(db_path)
    if not path.is_file(): raise ValueError('Plex database not found; set PLEX_DB to its exact path')
    # SQLite backup reads a consistent WAL-aware snapshot; source DB is never modified.
    uri='file:'+urllib.parse.quote(str(path))+'?mode=ro'
    src=sqlite3.connect(uri, uri=True, timeout=10)
    dst=sqlite3.connect(':memory:')
    try:
        src.backup(dst)
        dst.row_factory=sqlite3.Row
        sql='''SELECT m.id AS plex_id,
            CASE m.metadata_type WHEN 1 THEN 'Movie' WHEN 2 THEN 'Show' WHEN 4 THEN 'Episode' END AS type,
            ls.name AS library, m.library_section_id AS library_section_id, COALESCE(show.title,'') AS series_title, CASE WHEN m.metadata_type=2 THEN m.id ELSE show.id END AS series_id,
            m.title AS plex_title, m.original_title, m.year, m.guid,
            m.user_thumb_url AS poster_override, mp.file AS file_path,
            SUBSTR(m.summary,1,300) AS summary_excerpt,
            m."index" AS episode_number, season."index" AS season_number
            FROM metadata_items m
            LEFT JOIN library_sections ls ON ls.id=m.library_section_id
            LEFT JOIN metadata_items season ON season.id=m.parent_id AND m.metadata_type=4
            LEFT JOIN metadata_items show ON show.id=season.parent_id AND m.metadata_type=4
            LEFT JOIN media_items mi ON mi.id=(SELECT MIN(x.id) FROM media_items x WHERE x.metadata_item_id=m.id)
            LEFT JOIN media_parts mp ON mp.id=(SELECT MIN(x.id) FROM media_parts x WHERE x.media_item_id=mi.id)
            WHERE m.metadata_type IN (1,2,4) AND m.deleted_at IS NULL
            ORDER BY ls.name, m.title'''
        try: rows=dst.execute(sql).fetchall()
        except sqlite3.OperationalError as e:
            raise ValueError(f'Unsupported Plex DB schema: {e}. Import the exported CSV instead.')
        data=[normal_item(dict(x)) for x in rows]
        # Optional collection memberships are contextual clues; never blindly prepend them.
        tables={x[0] for x in dst.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if {'tags','taggings'} <= tables:
            try:
                coll=dst.execute("""SELECT g.metadata_item_id, GROUP_CONCAT(t.tag, ' | ') AS collections
                    FROM taggings g JOIN tags t ON t.id=g.tag_id
                    WHERE t.tag_type=2 GROUP BY g.metadata_item_id""").fetchall()
                collection_map={str(x[0]):x[1] for x in coll}
                for item in data:item['collections']=collection_map.get(item['plex_id'],'')
            except sqlite3.OperationalError:pass
        return derive_show_folders(data)
    finally: src.close(); dst.close()


def json_get(url, headers=None):
    req=urllib.request.Request(url,headers={'User-Agent':'PlexCurator/0.1 (+local metadata editor)','Accept':'application/json',**(headers or {})})
    try:
        with urllib.request.urlopen(req,timeout=12) as res: return json.load(res)
    except urllib.error.HTTPError as exc:
        if exc.code == 404: return None
        if exc.code == 429: raise ValueError('Metadata provider rate limit; retry after a pause')
        raise ValueError(f'Provider returned HTTP {exc.code}')
    except (TimeoutError,urllib.error.URLError) as exc:
        raise ValueError(f'Provider unavailable: {exc}')


def candidate(title,year,provider,url,score,poster='',description='',guid='',order=''):
    return {'title':title,'year':year or '', 'provider':provider,'source_url':url,'score':round(score,2),
            'poster_url':poster or '', 'description':description[:300], 'guid':guid, 'order':order}


def tmdb_lookup(item, token):
    if not token: return []
    title=file_title(item) or item.get('plex_title') or item.get('series_title')
    if not title: return []
    kind='tv' if item['type'] != 'Movie' else 'movie'
    q=urllib.parse.urlencode({'query':title, 'include_adult':'false'})
    data=json_get(f'https://api.themoviedb.org/3/search/{kind}?{q}', {'Authorization':'Bearer '+token}) or {}
    out=[]
    for entry in data.get('results',[])[:8]:
        name=entry.get('title') or entry.get('name') or ''
        year=(entry.get('release_date') or entry.get('first_air_date') or '')[:4]
        poster=('https://image.tmdb.org/t/p/w500'+entry['poster_path']) if entry.get('poster_path') else ''
        score=.76*max(similar(name,title),similar(name,item.get('plex_title',''))) + .24*(1 if year and str(item.get('year'))==year else .5)
        out.append(candidate(name,year,'TMDB',f'https://www.themoviedb.org/{kind}/{entry["id"]}',score,poster,entry.get('overview',''),f'tmdb://{kind}/{entry["id"]}'))
    return sorted(out,key=lambda x:-x['score'])


def tvmaze_lookup(item, order='aired'):
    show=item.get('series_title') or (item['plex_title'] if item['type']=='Show' else '')
    if not show:return []
    data=json_get('https://api.tvmaze.com/search/shows?'+urllib.parse.urlencode({'q':show})) or []
    results=[]
    for row in data[:5]:
        s=row['show']; sy=(s.get('premiered') or '')[:4]
        score=.7*similar(s.get('name',''),show) + .3*(1 if sy and sy==str(item.get('year')) else .55)
        results.append((score,s))
    if not results:return []
    results.sort(key=lambda x:-x[0]); selected=results[0][1]
    if item['type']=='Show':
        return [candidate(s['name'],(s.get('premiered') or '')[:4],'TVmaze',s['url'],score,(s.get('image') or {}).get('original',''),re.sub(r'<[^>]+>',' ',s.get('summary') or '')) for score,s in results]
    if item['type']!='Episode': return []
    season=item.get('season_number'); episode=item.get('episode_number')
    if not season or not episode:
        e=EPISODE.search(item.get('file_path') or '')
        if not e:return []
        season,episode=e[1],e[2]
    sid=selected['id']
    if order=='dvd':
        lists=json_get(f'https://api.tvmaze.com/shows/{sid}/alternatelists') or []
        dvd=[a for a in lists if a.get('dvd_premiere') or a.get('type')=='dvd_release']
        if not dvd:return []
        episodes=json_get(f'https://api.tvmaze.com/alternatelists/{dvd[0]["id"]}/alternateepisodes?embed=episodes') or []
        candidates=[]
        for e in episodes:
            if str(e.get('season')) != str(int(season)) or str(e.get('number')) != str(int(episode)):continue
            linked=e.get('_embedded',{}).get('episodes') or []
            base=(linked[0] if linked else {})
            name=e.get('name') or base.get('name') or ''
            if name: candidates.append(candidate(name, '', 'TVmaze DVD order',base.get('url') or selected['url'],.86, (base.get('image') or {}).get('original',''),'',order='dvd'))
        return candidates
    e=json_get(f'https://api.tvmaze.com/shows/{sid}/episodebynumber?'+urllib.parse.urlencode({'season':int(season),'number':int(episode)}))
    if not e:return []
    score=.65*max(similar(show,selected['name']),.5)+.35*(1 if similar(item.get('plex_title',''),e.get('name',''))>.8 else .72)
    return [candidate(e.get('name',''),(e.get('airdate') or '')[:4],'TVmaze aired order',e.get('url',selected['url']),score,(e.get('image') or {}).get('original',''),re.sub(r'<[^>]+>',' ',e.get('summary') or ''),order='aired')]


def wikidata_lookup(item):
    """Anonymous Wikidata film lookup; evidence only, never a Plex-agent GUID."""
    title=file_title(item) or item.get('plex_title','')
    if item.get('type')!='Movie' or not title:return []
    base='https://www.wikidata.org/w/api.php?'
    search=json_get(base+urllib.parse.urlencode({'action':'wbsearchentities','search':title,'language':'en','type':'item','limit':8,'format':'json'})) or {}
    found=search.get('search') or []
    ids=[x['id'] for x in found if re.fullmatch(r'Q\d+',x.get('id',''))]
    if not ids:return []
    raw=json_get(base+urllib.parse.urlencode({'action':'wbgetentities','ids':'|'.join(ids),'props':'labels|descriptions|claims','languages':'en','format':'json'})) or {}
    out=[]
    for key in ids:
        ent=raw.get('entities',{}).get(key,{})
        if ent.get('missing') is not None:continue
        name=ent.get('labels',{}).get('en',{}).get('value','')
        description=ent.get('descriptions',{}).get('en',{}).get('value','')
        claims=ent.get('claims',{})
        instance=[]
        for x in claims.get('P31',[]):
            try:instance.append(x['mainsnak']['datavalue']['value']['id'])
            except (KeyError,TypeError):pass
        if not ('film' in description.lower() or 'movie' in description.lower() or any(q in instance for q in ['Q11424','Q202866','Q506240','Q229390'])):
            continue
        year=''
        for x in claims.get('P577',[]):
            try:
                date=x['mainsnak']['datavalue']['value']['time']
                m=re.search(r'([12]\d{3})-',date)
                if m:year=m[1];break
            except (KeyError,TypeError):pass
        score=.78*max(similar(name,title),similar(name,item.get('plex_title','')))+.22*(1 if year and year==str(item.get('year','')) else .45)
        out.append(candidate(name,year,'Wikidata',f'https://www.wikidata.org/wiki/{key}',score,'',description))
    return sorted(out,key=lambda x:-x['score'])[:7]
