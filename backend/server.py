#!/usr/bin/env python3
"""Plex Curator backend. Read-only DB; opt-in Plex/file writes."""
import argparse, csv, io, json, os, re, tempfile, threading, time, urllib.parse, urllib.request, urllib.error, xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from engine import DB_DEFAULT, import_csv, import_db, diagnose, file_title, filename_proposal, folder_proposal, derive_show_folders, tmdb_lookup, tvmaze_lookup, wikidata_lookup, normal_item, year_evidence
from ssh_transport import SSHTransport
from remote_bridge import media_rename, folder_and_file_rename

ROOT=Path(__file__).resolve().parent.parent
STATE=ROOT/'data'; STATE.mkdir(exist_ok=True)
PLEX_URL=os.getenv('PLEX_URL','http://127.0.0.1:32400').rstrip('/')
PLEX_DB=os.getenv('PLEX_DB',DB_DEFAULT)
TMDB_TOKEN=os.getenv('TMDB_READ_TOKEN','')
MEDIA_ROOTS=[Path(p.strip()).resolve() for p in os.getenv('MEDIA_ROOTS','').split(':') if p.strip()]
SSH=SSHTransport()


def plex_token():
    if SSH.config:
        return SSH.token or os.getenv('PLEX_TOKEN', '')
    if os.getenv('PLEX_TOKEN'):return os.environ['PLEX_TOKEN']
    try:
        p=Path(PLEX_DB).parent.parent.parent/'Preferences.xml'
        return ET.parse(p).getroot().attrib.get('PlexOnlineToken','')
    except (OSError,ET.ParseError):return ''


def plex_request(method, route, params=None):
    token=plex_token()
    if not token:raise ValueError('Plex token missing. Set PLEX_TOKEN or make Preferences.xml readable.')
    query=('?'+urllib.parse.urlencode(params)) if params else ''
    request=urllib.request.Request(PLEX_URL+route+query, method=method, headers={'Accept':'application/json','X-Plex-Token':token,'X-Plex-Client-Identifier':'plex-curator-local','User-Agent':'PlexCurator/0.1'})
    try:
        with urllib.request.urlopen(request,timeout=16) as response: body=response.read()
    except urllib.error.HTTPError as e:
        extra=e.read(500).decode('utf-8','replace').strip().replace('\n',' ')
        raise ValueError(f'Plex API {method} {route}: HTTP {e.code}' + (f' ({extra[:180]})' if extra and '<html' not in extra.lower() else ''))
    except urllib.error.URLError as e: raise ValueError(f'Cannot reach Plex API: {e.reason}')
    if not body:return {}
    try:return json.loads(body)
    except ValueError:
        try:
            root=ET.fromstring(body)
            # Plex often responds with XML even when JSON was requested. Preserve
            # SearchResult / Photo types instead of incorrectly labeling as Metadata.
            container={'_attributes': dict(root.attrib)}
            for child in root:
                kind=child.tag.split('}')[-1]
                container.setdefault(kind, []).append(dict(child.attrib))
            return {'MediaContainer':container}
        except ET.ParseError:return {}


def plex_metadata(pid):
    data=plex_request('GET',f'/library/metadata/{int(pid)}')
    container=data.get('MediaContainer',{})
    rows=container.get('Metadata',[]) or container.get('Video',[]) or container.get('Directory',[])
    if not rows:raise ValueError(f'Plex ID {pid} no longer exists')
    return rows[0]


def plex_posters(pid):
    data=plex_request('GET',f'/library/metadata/{int(pid)}/posters')
    container=data.get('MediaContainer',{})
    images=container.get('Photo',[]) or container.get('Metadata',[])
    if isinstance(images,dict):images=[images]
    output=[]
    for x in images:
        if not isinstance(x,dict):continue
        key=str(x.get('ratingKey') or x.get('key') or '')
        if not key:continue
        output.append({**x,'ratingKey':key,
                       'selected':str(x.get('selected','0')).lower() in ('1','true'),
                       'thumb':str(x.get('thumb') or x.get('key') or '')})
    return output


def plex_matches(pid):
    route=f'/library/metadata/{int(pid)}/matches'
    # GET is supported by standard PMS releases. Some API specifications also
    # document PUT, so retry only for a route/method failure.
    try:data=plex_request('GET',route,{'manual':1})
    except ValueError as e:
        if not ('HTTP 404' in str(e) or 'HTTP 405' in str(e)):raise
        try:data=plex_request('PUT',route,{'manual':1})
        except ValueError as alt:
            raise ValueError(f'Plex match lookup unavailable: {e}; alternate method: {alt}') from alt
    container=data.get('MediaContainer',{})
    results=container.get('SearchResult',[]) or container.get('Metadata',[])
    if isinstance(results,dict):results=[results]
    return [dict(x) for x in results if isinstance(x,dict)]


def plex_image(path, pid):
    # Server-side image proxy only: never fetch arbitrary external URLs.
    parsed=urllib.parse.urlsplit(path)
    allowed=f'/library/metadata/{int(pid)}/'
    if not parsed.path.startswith(allowed) or parsed.scheme or parsed.netloc:
        raise ValueError('Invalid Plex image path')
    token=plex_token()
    if not token:raise ValueError('Plex token missing')
    url=PLEX_URL+path
    request=urllib.request.Request(url,headers={'X-Plex-Token':token,'Accept':'image/*'})
    try:
        with urllib.request.urlopen(request,timeout=16) as response:
            content_type=response.headers.get('Content-Type','').split(';',1)[0].lower()
            blob=response.read(5_000_001)
    except urllib.error.HTTPError as e:raise ValueError(f'Plex poster image: HTTP {e.code}')
    except urllib.error.URLError as e:raise ValueError(f'Plex poster image: {e.reason}')
    if not content_type.startswith('image/') or len(blob)>5_000_000:
        raise ValueError('Plex poster returned no supported image')
    return blob,content_type


def verify_poster(pid, expected_key):
    # Plex can respond 200 to a poster change before the selected image updates.
    for delay in (0,0.4,0.8,1.2):
        if delay:time.sleep(delay)
        posters=plex_posters(pid)
        if any(x['ratingKey']==expected_key and x['selected'] for x in posters):return True
    return False


def validate_local_rename(old, newname, apply=False):
    # Use the same no-overwrite checks and move primitive as the SSH bridge.
    return media_rename({'source':old,'new_name':newname,
                         'roots':[str(r) for r in MEDIA_ROOTS]}, apply)


def safe_path(old, newname):
    # Compatibility with old callers: returns source + target Path objects.
    paths = validate_local_rename(old, newname)
    return Path(paths['old_file']), Path(paths['new_file'])


def item_folder(row):
    if row.get('type') == 'Movie' and row.get('file_path'):
        return str(PurePosixPath(row['file_path']).parent)
    if row.get('type') == 'Show':
        return row.get('folder_path') or ''
    return ''


def assert_folder_ownership(pid, folder):
    """Prevent moving directories holding other movies or unrelated series."""
    row = LIB.rows[pid]
    if row.get('type') not in ('Movie', 'Show'):
        raise ValueError('Folder rename is only available for movies or entire TV series, not episodes/seasons')
    if not folder or not folder.startswith('/') or folder == '/':
        raise ValueError('No unambiguous media folder for this item; refresh Plex DB')
    base = PurePosixPath(folder)
    for other_id, other in LIB.rows.items():
        if other_id == pid: continue
        location = other.get('file_path') or ''
        if not location or not PurePosixPath(location).is_relative_to(base):
            continue
        if row['type'] == 'Show' and other.get('type') == 'Episode' and row.get('series_id') and str(other.get('series_id')) == str(row['series_id']):
            continue
        raise ValueError(f'Folder also contains unrelated Plex #{other_id}; cannot safely rename an entire directory')


def preview_media_operation(pid, filename='', folder=''):
    row = LIB.rows[pid]
    old_file = row.get('file_path') or ''
    if folder:
        if not (LIB.source.startswith('SSH:') or 'Plex SQLite' in LIB.source):
            raise ValueError('Folder moves require a fresh Plex database snapshot. Use Connect via SSH (or Load DB), not an imported CSV.')
        source_folder = item_folder(row)
        assert_folder_ownership(pid, source_folder)
        if SSH.config:
            return SSH.rename_bundle(old_file,source_folder,filename,folder,False)
        return folder_and_file_rename({'source':old_file, 'folder_source':source_folder,
            'new_name':filename, 'new_folder':folder,'roots':[str(x) for x in MEDIA_ROOTS]},False)
    if not old_file:raise ValueError('No file path for this item')
    return SSH.rename(old_file,filename,False) if SSH.config else validate_local_rename(old_file,filename)


def request_scan_for_rename(pid, new_path, section_id):
    if not section_id or not str(section_id).isdigit():
        raise ValueError('Library section ID unavailable. Scan the library manually in Plex.')
    # Plex queues a partial scan; the response does NOT mean it has completed.
    plex_request('POST', f'/library/sections/{int(section_id)}/refresh',
                 {'path': str(Path(new_path).parent)})
    return {'queued':True,'section_id':str(section_id),'folder':str(Path(new_path).parent),
            'message':'Plex accepted a partial scan request; wait for the scan to finish before refreshing the Curator database.'}


def scan_confirmed_renames(renames):
    """Queue partial scans for successfully renamed files only, one per folder/section.

    The caller cannot choose arbitrary Plex paths or section IDs: both values
    must come from the local successful-rename audit journal.
    """
    if not isinstance(renames, list) or not 1 <= len(renames) <= 500:
        raise ValueError('Supply between 1 and 500 completed file renames')
    if SSH.config and not SSH.connected:
        raise ValueError('Reconnect to Plex before requesting a scan')
    history=STATE/'changes.jsonl'
    if not history.exists():
        raise ValueError('No completed renames in change history')
    # Walk backward so the most recent matching successful rename wins.
    index={}
    for line in reversed(history.read_text(encoding='utf-8').splitlines()[-10000:]):
        try:entry=json.loads(line)
        except ValueError:continue
        if entry.get('status')=='failed' or not set(entry.get('changes',[])).intersection({'filename','folder'}):continue
        key=(str(entry.get('plex_id','')),str(entry.get('scan_path') or entry.get('new_file','')))
        if key not in index:index[key]=entry
    groups={}
    seen=set()
    for requested in renames:
        if not isinstance(requested,dict):raise ValueError('Rename entry must be an object')
        pid=str(requested.get('id',''))
        filepath=requested.get('new_file','')
        if not pid.isdigit() or not isinstance(filepath,str) or not filepath.startswith('/'):
            raise ValueError('Invalid Plex ID or absolute media path')
        key=(pid,filepath)
        if key in seen:continue
        seen.add(key)
        entry=index.get(key)
        if not entry:raise ValueError(f'Plex #{pid}: file rename not confirmed in the change journal')
        section_id=str(entry.get('section_id') or '')
        if not section_id.isdigit():raise ValueError(f'Plex #{pid}: missing library section ID')
        # SSH targets a Linux Plex server even when the editor runs on Windows.
        # Use POSIX paths and reject malformed paths; never trust a client folder.
        folder=str(entry.get('scan_folder') or PurePosixPath(filepath).parent)
        if folder in ('/', '.'):
            raise ValueError('Cannot scan a filesystem root')
        group=(section_id,folder)
        if group not in groups:groups[group]={'section_id':section_id,'folder':folder,'ids':[],'files':[]}
        groups[group]['ids'].append(pid)
        groups[group]['files'].append(filepath)
    results=[]
    for (section_id, folder), batch in groups.items():
        try:
            # Response means queued, not completed; do not use force=1.
            plex_request('POST',f'/library/sections/{int(section_id)}/refresh',{'path':folder})
            outcome={**batch,'ok':True,'queued':True}
            with (STATE/'changes.jsonl').open('a',encoding='utf-8') as log:
                log.write(json.dumps({'at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                    'changes':['scan_requested'],'section_id':section_id,'folder':folder,
                    'ids':batch['ids']},ensure_ascii=False)+'\n')
        except Exception as e:
            outcome={**batch,'ok':False,'queued':False,'error':str(e)}
        results.append(outcome)
    count=sum(bool(x['ok']) for x in results)
    return {'requested_files':len(seen),'unique_folders':len(results),
            'queued_folders':count,'failed_folders':len(results)-count,'results':results,
            'message':f'Plex accepted {count}/{len(results)} folder scan requests; scans may still be running.'}


def atomic_json(path, data):
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False, encoding='utf-8') as temp:
        json.dump(data,temp,indent=2,ensure_ascii=False); temp.flush();os.fsync(temp.fileno()); name=temp.name
    os.replace(name,path)


class Library:
    def __init__(self):
        self.lock=threading.RLock(); self.rows={}; self.decisions={}; self.lookup={}; self.source='No library loaded'
        path=STATE/'decisions.json'
        if path.exists():
            try:self.decisions=json.loads(path.read_text())
            except (OSError,ValueError):pass

    def load(self,rows,source):
        with self.lock:
            self.rows={str(x['plex_id']):x for x in derive_show_folders(rows) if x.get('plex_id')}
            self.source=source;self.lookup={}
            # Never reuse an approval after the row's identity changes.
            self.decisions={k:v for k,v in self.decisions.items() if k in self.rows and v.get('identity')==self.identity(self.rows[k])}
            self.save()

    @staticmethod
    def identity(item):return '|'.join((item.get('guid',''),item.get('file_path',''),item.get('folder_path',''),item.get('plex_title',''),str(item.get('year',''))))

    def save(self):atomic_json(STATE/'decisions.json',self.decisions)

    def decorated(self, pid):
        item=self.rows[pid].copy();item['diagnostic']=diagnose(item)
        item['decision']=self.decisions.get(pid,{'approved':False,'title':'','year':'','filename':'','poster_url':'','poster_key':'','match_guid':'','folder':''})
        item['candidates']=self.lookup.get(pid,[])
        return item

    def listing(self,filters):
        q=(filters.get('q',[''])[0]).lower().strip(); media_type=filters.get('type',['all'])[0]
        flagged=filters.get('flagged',['false'])[0]=='true';offset=max(0,int(filters.get('offset',['0'])[0]));limit=min(250,max(1,int(filters.get('limit',['80'])[0])))
        with self.lock:
            items=[];stats={'Movie':0,'Show':0,'Episode':0,'flagged':0,'reviewed':0}
            for pid, row in self.rows.items():
                stats[row['type']]=stats.get(row['type'],0)+1
                issues=diagnose(row)['issues']
                if issues:stats['flagged']+=1
                if self.decisions.get(pid,{}).get('approved'): stats['reviewed']+=1
                if media_type!='all' and row['type']!=media_type:continue
                if flagged and not issues:continue
                if q and q not in ' '.join(str(row.get(k,'')) for k in ['plex_id','plex_title','series_title','file_path','guid']).lower():continue
                items.append(pid)
            items.sort(key=lambda pid:(0 if diagnose(self.rows[pid])['issues'] else 1, (self.rows[pid].get('series_title') or self.rows[pid].get('plex_title') or '').lower(),int(pid)))
            return {'items':[self.decorated(x) for x in items[offset:offset+limit]],'total':len(items),'stats':stats,'source':self.source}

    def set_decision(self,pid,body):
        with self.lock:
            if pid not in self.rows:raise ValueError('Unknown Plex ID')
            before=self.decisions.get(pid,{})
            allowed=['title','year','filename','folder','poster_url','poster_key','match_guid','approved']
            v={k:body.get(k,before.get(k,False if k=='approved' else '')) for k in allowed}
            for k in ('title','year','filename','folder','poster_url','poster_key','match_guid'):
                if not isinstance(v[k],str) or len(v[k])>800:raise ValueError(f'Invalid {k}')
                v[k]=v[k].strip()
            if not isinstance(v['approved'],bool):raise ValueError('approved must be true or false')
            if v['year'] and (not re.fullmatch(r'\d{4}', v['year']) or not 1888 <= int(v['year']) <= __import__('datetime').date.today().year + 1):
                raise ValueError('Year must be a valid 4-digit release year')
            if v['filename'] and any(x in v['filename'] for x in ['/', '\\', '\x00']):raise ValueError('Filename must not include directory separators')
            if v['folder'] and (self.rows[pid]['type'] not in ('Movie','Show') or v['folder'] in ('.','..') or len(v['folder'])>240 or v['folder'].endswith((' ','.')) or any(c in v['folder'] for c in ('/','\\','\x00'))):
                raise ValueError('Invalid folder name or unsupported media type')
            if v['title'] and ('\x00' in v['title'] or len(v['title'])>250):raise ValueError('Invalid title')
            # One poster source per proposal. Choosing Plex artwork replaces a URL and vice versa.
            if body.get('poster_key'):v['poster_url']=''
            elif body.get('poster_url'):v['poster_key']=''
            # Editing any proposed value resets previous approval.
            if any(v[k]!=before.get(k,'') for k in allowed if k!='approved'):v['approved']=False
            v['identity']=self.identity(self.rows[pid]); self.decisions[pid]=v;self.save()
            return self.decorated(pid)

    def stage_years(self, ids):
        if not isinstance(ids,list) or not 1 <= len(ids) <= 250:
            raise ValueError('Select 1–250 rows to stage year corrections')
        changes=[]; skipped=[]
        with self.lock:
            for requested in dict.fromkeys(str(x) for x in ids):
                item=self.rows.get(requested)
                if not item:
                    skipped.append({'id':requested,'reason':'ID is not in the current library'})
                    continue
                proof=year_evidence(item)
                if not proof['batch_safe']:
                    skipped.append({'id':requested,'reason':proof['explanation'] or 'No two-source movie year mismatch'})
                    continue
                old=self.decisions.get(requested,{})
                proposed=proof['proposed_year']
                if old.get('year')==proposed:
                    skipped.append({'id':requested,'reason':'That year is already staged'})
                    continue
                self.set_decision(requested,{'year':proposed})
                changes.append({'id':requested,'title':item.get('plex_title',''),
                                'old_year':item.get('year',''), 'new_year':proposed,
                                'approved':False})
        return {'staged':changes, 'skipped':skipped}

    def export(self):
        output=io.StringIO(); w=csv.writer(output)
        w.writerow(['plex_id','type','library','series_title','collections','current_title','current_year','file_path','guid','issues','recommended_title','recommended_year','proposed_title','proposed_year','proposed_filename','proposed_folder','proposed_poster_url','proposed_match_guid','approved'])
        for pid,item in self.rows.items():
            d=self.decisions.get(pid,{});a=diagnose(item)
            if not a['issues'] and not d:continue
            w.writerow([pid,item['type'],item.get('library',''),item.get('series_title',''),item.get('collections',''),item.get('plex_title',''),item.get('year',''),item.get('file_path',''),item.get('guid',''),'; '.join(a['issues']),a['proposed_title'],a['year_evidence']['proposed_year'],d.get('title',''),d.get('year',''),d.get('filename',''),d.get('folder',''),d.get('poster_url',''),d.get('match_guid',''),d.get('approved',False)])
        return output.getvalue()


LIB=Library()

def apply_one(pid):
    with LIB.lock:
        row=LIB.rows.get(pid);d=LIB.decisions.get(pid,{})
        if not row:raise ValueError('Plex ID not found in current import')
        if not d.get('approved'):raise ValueError('Not approved')
        if LIB.source.startswith('SSH:') and not SSH.connected:
            raise ValueError('SSH connection was lost; reconnect and refresh before applying')
        if d.get('identity')!=LIB.identity(row):raise ValueError('Stale approval; reimport and reapprove')
        updates={k:d.get(k,'') for k in ['title','year','filename','folder','poster_url','poster_key','match_guid']}
        if not any(updates.values()):raise ValueError('No proposed changes')
        live=plex_metadata(pid)
        if live.get('title','')!=row.get('plex_title',''):raise ValueError('Plex title changed since import; reload library')
        if row.get('guid') and live.get('guid') and live['guid']!=row['guid']:raise ValueError('Plex GUID changed; reimport')
        if updates['year'] and str(live.get('year') or '') != str(row.get('year') or ''):
            raise ValueError('Plex year changed since import; reload library')
        if updates['poster_url']:
            url=urllib.parse.urlparse(updates['poster_url'])
            if url.scheme!='https' or url.hostname not in {'image.tmdb.org','static.tvmaze.com'}:raise ValueError('Poster URL must come from TMDB or TVmaze')
        if updates['match_guid']:
            options=plex_matches(pid)
            if updates['match_guid'] not in [str(x.get('guid')) for x in options]:raise ValueError('Plex rematch GUID no longer offered by Plex')
        if updates['poster_key']:
            if updates['poster_key'] not in [str(x.get('ratingKey')) for x in plex_posters(pid)]:raise ValueError('Poster option no longer exists')
        if SSH.config and not SSH.connected:
            raise ValueError('SSH connection was lost; reconnect and refresh before applying')
        if updates['filename'] or updates['folder']:
            paths=preview_media_operation(pid,updates['filename'],updates['folder'])
        else:
            paths=None
        changes=[]
        attempted=[]
        try:
            if updates['match_guid'] and updates['match_guid']!=row.get('guid'):
                attempted.append('rematch')
                plex_request('PUT',f'/library/metadata/{int(pid)}/match',{'guid':updates['match_guid']})
                for pause in (0,0.5,1,1.5):
                    if pause:time.sleep(pause)
                    if plex_metadata(pid).get('guid')==updates['match_guid']:break
                else:raise ValueError('Plex accepted rematch but new GUID was not confirmed; verify Plex before retrying')
                changes.append('rematch')
            # Update only changed scalar fields. Lock edits against Plex metadata refresh.
            metadata_changes={}
            if updates['title'] and updates['title']!=row.get('plex_title'):
                metadata_changes.update({'title.value':updates['title'],'title.locked':1})
            if updates['year'] and updates['year']!=str(row.get('year') or ''):
                metadata_changes.update({'year.value':updates['year'],'year.locked':1})
            if metadata_changes:
                attempted.append('metadata_edit')
                plex_request('PUT',f'/library/metadata/{int(pid)}',metadata_changes)
                if 'title.value' in metadata_changes:changes.append('title')
                if 'year.value' in metadata_changes:changes.append('year')
                # Some Plex builds report success despite ignoring a field; fail safely.
                now=plex_metadata(pid)
                if 'year' in changes and str(now.get('year') or '')!=updates['year']:
                    raise ValueError('Plex did not persist the new release year')
                if 'title' in changes and now.get('title')!=updates['title']:
                    raise ValueError('Plex did not persist the new title')
            if updates['poster_key']:
                attempted.append('poster_selection')
                plex_request('PUT',f'/library/metadata/{int(pid)}/poster',{'url':updates['poster_key']})
                if not verify_poster(pid,updates['poster_key']):
                    raise ValueError('Plex accepted poster selection but did not confirm it as selected; check Plex before retrying')
                changes.append('poster')
            if updates['poster_url']:
                attempted.append('poster_upload')
                old_keys={str(x.get('ratingKey')) for x in plex_posters(pid)}
                plex_request('POST',f'/library/metadata/{int(pid)}/posters',{'url':updates['poster_url']})
                uploaded=[]
                for delay in (0,0.5,1,1.5):
                    if delay:time.sleep(delay)
                    new_posters=plex_posters(pid)
                    uploaded=[x for x in new_posters if x.get('ratingKey') and str(x['ratingKey']) not in old_keys]
                    if uploaded:break
                if len(uploaded)!=1:
                    raise ValueError('Plex accepted poster upload, but the uploaded image could not be identified and selected; review Plex posters before retrying')
                selected_key=uploaded[0]['ratingKey']
                attempted.append('poster_selection')
                plex_request('PUT',f'/library/metadata/{int(pid)}/poster',{'url':selected_key})
                if not verify_poster(pid,selected_key):
                    raise ValueError('Poster was uploaded, but Plex did not confirm its selection; check Plex before retrying')
                changes.extend(['poster_uploaded','poster_selected'])
            if paths:
                attempted.append('folder_rename' if updates['folder'] else 'filename_rename')
                if updates['folder']:
                    assert_folder_ownership(pid,item_folder(row))
                    if SSH.config:
                        paths=SSH.rename_bundle(row.get('file_path',''),item_folder(row),updates['filename'],updates['folder'],True)
                    else:
                        paths=folder_and_file_rename({'source':row.get('file_path',''),'folder_source':item_folder(row),
                           'new_name':updates['filename'],'new_folder':updates['folder'],
                           'roots':[str(x) for x in MEDIA_ROOTS]},True)
                    changes.append('folder')
                    if updates['filename']: changes.append('filename')
                else:
                    paths=SSH.rename(row.get('file_path',''),updates['filename'],True) if SSH.config else validate_local_rename(row.get('file_path',''), updates['filename'], True)
                    changes.append('filename')
        except Exception as operation_error:
            # Only roll back known-reversible edits immediately.
            if 'filename' in changes and 'folder' not in changes and paths:
                try:
                    if SSH.config: SSH.rename(paths['new_file'],Path(paths['old_file']).name,True)
                    else:validate_local_rename(paths['new_file'], Path(paths['old_file']).name, True)
                except (OSError, ValueError):pass
            rollback={}
            if 'title' in changes:rollback.update({'title.value':row['plex_title'],'title.locked':1})
            if 'year' in changes and row.get('year'):
                rollback.update({'year.value':row['year'],'year.locked':1})
            rollback_ok=None
            if rollback:
                try:
                    plex_request('PUT',f'/library/metadata/{int(pid)}',rollback)
                    rollback_ok=True
                except Exception:
                    rollback_ok=False
            if attempted:
                failure={'at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                         'plex_id':pid,'status':'failed','changes':changes,
                         'attempted':attempted,'error':str(operation_error),
                         'rollback_attempted':bool(rollback),'rollback_request_accepted':rollback_ok,
                         'note':'Plex may have applied part of this operation. Inspect the item and reload the DB before resubmitting.'}
                with (STATE/'changes.jsonl').open('a',encoding='utf-8') as log:
                    log.write(json.dumps(failure,ensure_ascii=False)+'\n')
                LIB.decisions.pop(pid,None);LIB.save()
            raise
        if 'title' in changes: row['plex_title']=updates['title']
        if 'year' in changes: row['year']=updates['year']
        if 'folder' in changes:
            before_folder=PurePosixPath(paths['old_folder']); after_folder=PurePosixPath(paths['new_folder'])
            for other_id, other in LIB.rows.items():
                for key in ('file_path','folder_path'):
                    old_value=other.get(key) or ''
                    if old_value and PurePosixPath(old_value).is_relative_to(before_folder):
                        other[key] = str(after_folder / PurePosixPath(old_value).relative_to(before_folder))
                        if other_id!=pid: LIB.decisions.pop(other_id,None)
        if 'filename' in changes:row['file_path']=paths['new_file']
        if 'rematch' in changes:row['guid']=updates['match_guid']
        entry={'at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'plex_id':pid,'changes':changes,'before':{k:row.get(k,'') for k in []},
               'old_title':live.get('title',''),'new_title':updates['title'] or live.get('title',''),
               'old_year':str(live.get('year') or ''),'new_year':updates['year'] or str(live.get('year') or ''),
               'old_file':paths['old_file'] if paths else '',
               'new_file':paths['new_file'] if paths else '',
               'old_folder':paths.get('old_folder','') if paths else '',
               'new_folder':paths.get('new_folder','') if paths else '',
               'scan_path':paths.get('scan_path') or paths.get('new_file','') if paths else '',
               'scan_folder':paths.get('scan_folder') or str(PurePosixPath(paths['new_file']).parent) if paths else '',
               'rename_method':paths.get('method','') if paths else '',
               'section_id':str(row.get('library_section_id') or live.get('librarySectionID') or ''),
               'rollback_limits':'Artwork selection and provider rematch require manual reversal'}
        with (STATE/'changes.jsonl').open('a') as f:f.write(json.dumps(entry,ensure_ascii=False)+'\n')
        # Updated rows invalidate approvals to prevent accidental repeats.
        LIB.decisions.pop(pid,None);LIB.save()
        return entry


class Handler(BaseHTTPRequestHandler):
    server_version='PlexCurator/0.1'
    def log_message(self,format,*args): pass
    def json(self,status,data):
        body=json.dumps(data,ensure_ascii=False).encode();self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def fail(self,e):self.json(400,{'error':str(e)})
    def image(self,data,kind):
        self.send_response(200);self.send_header('Content-Type',kind)
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def body(self):
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('JSON body required')
        length=int(self.headers.get('Content-Length','0'))
        if length<=0 or length>28_000_000:raise ValueError('Invalid body size')
        return json.loads(self.rfile.read(length))
    def origin_ok(self):
        # Writes are accepted from the exact host/port serving the web UI,
        # including LAN addresses when the service binds to 0.0.0.0.
        origin=self.headers.get('Origin','')
        if not origin:return True  # CLI/API clients do not send Origin.
        try:
            parsed=urllib.parse.urlsplit(origin)
            return (parsed.scheme in ('http','https')
                    and parsed.netloc.lower()==self.headers.get('Host','').lower()
                    and parsed.path in ('','/')
                    and not parsed.query and not parsed.fragment
                    and parsed.username is None and parsed.password is None)
        except ValueError:
            return False
    def do_GET(self):
        try:
            route=urllib.parse.urlparse(self.path);parts=route.path.strip('/').split('/')
            q=urllib.parse.parse_qs(route.query)
            if route.path=='/api/status':return self.json(200,{'source':LIB.source,'total':len(LIB.rows),'plex_token':bool(plex_token()),'plex_url':PLEX_URL,'db_exists':SSH.connected or Path(PLEX_DB).is_file(),'tmdb_enabled':bool(TMDB_TOKEN),'media_roots':SSH.config['media_roots'] if SSH.config else [str(x) for x in MEDIA_ROOTS], 'ssh_connected':SSH.connected, 'ssh_config':SSH.config})
            if route.path=='/api/items':return self.json(200,LIB.listing(q))
            if len(parts)==3 and parts[:2]==['api','items']:
                with LIB.lock:return self.json(200,LIB.decorated(parts[2]))
            if route.path=='/api/export':
                data=LIB.export().encode('utf-8-sig');self.send_response(200);self.send_header('Content-Type','text/csv; charset=utf-8');self.send_header('Content-Disposition','attachment; filename="plex-curator-audit.csv"');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
            if route.path=='/api/logs':
                path=STATE/'changes.jsonl'; lines=path.read_text().splitlines()[-70:] if path.exists() else []
                return self.json(200,[json.loads(x) for x in reversed(lines)])
            if len(parts)==3 and parts[:2]==['api','plex-matches']:
                if parts[2] not in LIB.rows:raise ValueError('Unknown ID')
                results=plex_matches(parts[2]);return self.json(200,results[:20])
            if len(parts)==3 and parts[:2]==['api','plex-posters']:
                if parts[2] not in LIB.rows:raise ValueError('Unknown ID')
                return self.json(200,plex_posters(parts[2])[:30])
            if len(parts)==4 and parts[:2]==['api','poster-choice']:
                pid,ordinal=parts[2],parts[3]
                if pid not in LIB.rows or not ordinal.isdigit():raise ValueError('Invalid poster selection')
                choices=plex_posters(pid)
                idx=int(ordinal)
                if idx>=min(100,len(choices)):raise ValueError('Poster no longer available')
                path=choices[idx].get('thumb','')
                data,kind=plex_image(path,pid)
                return self.image(data,kind)
            if len(parts)==3 and parts[:2]==['api','poster']:
                if parts[2] not in LIB.rows:raise ValueError('Unknown ID')
                metadata=plex_metadata(parts[2]);thumb=metadata.get('thumb','')
                if not thumb or not thumb.startswith('/'):raise ValueError('No Plex poster available')
                data,kind=plex_image(thumb,parts[2])
                return self.image(data,kind)
            # Optional static production frontend.
            index=ROOT/'web'/'dist'/'index.html'
            if index.exists() and not route.path.startswith('/api'):
                requested=(ROOT/'web'/'dist'/route.path.lstrip('/')).resolve()
                if not requested.is_relative_to((ROOT/'web'/'dist').resolve()) or not requested.is_file():requested=index
                mimetype='text/html' if requested.suffix=='.html' else 'application/javascript' if requested.suffix=='.js' else 'text/css' if requested.suffix=='.css' else 'image/svg+xml' if requested.suffix=='.svg' else 'application/octet-stream'
                data=requested.read_bytes();self.send_response(200);self.send_header('Content-Type',mimetype);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
            return self.json(404,{'error':'Not found'})
        except Exception as e:self.fail(e)
    def do_POST(self):
        if not self.origin_ok():return self.json(403,{'error':'Same-origin requests only'})
        try:
            p=self.path;body=self.body()
            if p=='/api/connect':
                global PLEX_URL
                rows=SSH.connect(body)
                PLEX_URL=f'http://127.0.0.1:{SSH.local_port}'
                LIB.load([normal_item(x) for x in rows],f"SSH: {SSH.config['user']}@{SSH.config['host']} (read-only SQLite snapshot)")
                return self.json(200,{'count':len(rows),'connected':True,'token_found':bool(plex_token())})
            if p=='/api/disconnect':
                SSH.close()
                LIB.load([], 'Disconnected')
                PLEX_URL=os.getenv('PLEX_URL','http://127.0.0.1:32400').rstrip('/')
                return self.json(200,{'connected':False})
            if p=='/api/import':
                rows=import_csv(body.get('csv',''));LIB.load(rows,'Uploaded CSV');return self.json(200,{'count':len(rows)})
            if p=='/api/load-db':
                if SSH.config:
                    rows=[normal_item(x) for x in SSH.call({'op':'load','db':SSH.config['db']})['rows']]
                    LIB.load(rows,f"SSH: {SSH.config['host']} (read-only SQLite snapshot)")
                else:
                    rows=import_db(PLEX_DB);LIB.load(rows,'Local Plex SQLite (read-only snapshot)')
                return self.json(200,{'count':len(rows)})
            if p=='/api/lookup':
                pid=str(body.get('id',''));provider=body.get('provider','all');order=body.get('order','aired')
                if pid not in LIB.rows:raise ValueError('Unknown ID')
                if provider not in ('all','tmdb','tvmaze','wikidata') or order not in ('aired','dvd'):raise ValueError('Unsupported provider or episode order')
                item=LIB.rows[pid];answers=[];errors=[]
                if provider in ('all','wikidata') and item['type']=='Movie':
                    try:answers+=wikidata_lookup(item)
                    except ValueError as e:errors.append(str(e))
                if provider in ('all','tvmaze') and item['type']!='Movie':
                    try:answers+=tvmaze_lookup(item,order)
                    except ValueError as e:errors.append(str(e))
                if provider in ('all','tmdb') and TMDB_TOKEN and item['type'] in ('Movie','Show'):
                    try:answers+=tmdb_lookup(item,TMDB_TOKEN)
                    except ValueError as e:errors.append(str(e))
                answers.sort(key=lambda x:-x['score']);LIB.lookup[pid]=answers
                return self.json(200,{'results':answers,'errors':errors})
            if p=='/api/suggest-filename':
                pid=str(body.get('id',''));title=body.get('title',''); year=body.get('year','')
                if pid not in LIB.rows or not isinstance(title,str) or len(title)>250:raise ValueError('Invalid item or title')
                if year and (not isinstance(year,str) or not re.fullmatch(r'\d{4}',year)):
                    raise ValueError('Proposed year must be four digits')
                return self.json(200,{'filename':filename_proposal(LIB.rows[pid],title,year=year,force=True)})
            if p=='/api/decision':
                pid=str(body.get('id',''));return self.json(200,LIB.set_decision(pid,body))
            if p=='/api/suggest-folder':
                pid=str(body.get('id','')); title=body.get('title',''); year=body.get('year','')
                if pid not in LIB.rows or not isinstance(title,str) or len(title)>250:raise ValueError('Invalid record or proposed title')
                if year and (not isinstance(year,str) or not re.fullmatch(r'\d{4}',year)):
                    raise ValueError('Year must be four digits')
                row=LIB.rows[pid]
                return self.json(200,{'folder':folder_proposal(row,title,year),'current_folder':item_folder(row)})
            if p=='/api/validate-folder':
                pid=str(body.get('id','')); folder=body.get('folder',''); filename=body.get('filename','')
                if pid not in LIB.rows:raise ValueError('Unknown Plex ID')
                if not isinstance(folder,str) or not isinstance(filename,str) or not folder:
                    raise ValueError('Enter a proposed folder name')
                paths=preview_media_operation(pid,filename,folder)
                return self.json(200,{'ready':True,**paths,
                    'message':'Preview only. Moving this directory also moves every subtitle, season, and media file it contains.'})
            if p=='/api/validate-filename':
                pid=str(body.get('id','')); name=body.get('filename','')
                if pid not in LIB.rows:raise ValueError('Unknown Plex ID')
                if not isinstance(name,str):raise ValueError('Filename must be text')
                source=LIB.rows[pid].get('file_path','')
                if not source:raise ValueError('No file path for this Plex item')
                if SSH.config:
                    paths=SSH.rename(source,name,False)
                else:
                    paths=validate_local_rename(source,name)
                return self.json(200,{'ready':True,'old_file':paths['old_file'],
                                      'new_file':paths['new_file'],
                                      'message':'Ready. No changes have been made. Approval and Apply are still required.'})
            if p=='/api/scan-rename':
                result=scan_confirmed_renames([{'id':body.get('id'),'new_file':body.get('new_file')}])
                if result['failed_folders']:
                    raise ValueError(result['results'][0]['error'])
                return self.json(200,{'queued':True,'section_id':result['results'][0]['section_id'],'folder':result['results'][0]['folder'],
                                      'message':result['message']})
            if p=='/api/scan-renames':
                return self.json(200,scan_confirmed_renames(body.get('renames')))
            if p=='/api/stage-years':
                return self.json(200, LIB.stage_years(body.get('ids',[])))
            if p=='/api/apply':
                if body.get('confirm')!='APPLY':raise ValueError('Explicit confirmation required')
                ids=body.get('ids',[])
                if not isinstance(ids,list) or len(ids)>20:raise ValueError('Maximum 20 items per batch')
                result=[]
                for pid in ids:
                    try:result.append({'id':str(pid),'ok':True,'data':apply_one(str(pid))})
                    except Exception as e:result.append({'id':str(pid),'ok':False,'error':str(e)})
                return self.json(200,{'results':result})
            return self.json(404,{'error':'Not found'})
        except Exception as e:self.fail(e)


def main():
    parser=argparse.ArgumentParser(description='Plex Curator — read-only Plex DB + metadata UI')
    parser.add_argument('--csv',help='Preload a Plex metadata CSV export')
    parser.add_argument('--db',action='store_true',help='Load local SQLite DB at startup')
    parser.add_argument('--host',default=os.getenv('CURATOR_HOST','0.0.0.0'),
                        help='Bind address (default: 0.0.0.0; 127.0.0.1 for local-only)')
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    if args.csv:LIB.load(import_csv(Path(args.csv).read_text(encoding='utf-8-sig')),f'CSV: {Path(args.csv).name}')
    elif args.db:LIB.load(import_db(PLEX_DB),'Plex SQLite (read-only snapshot)')
    print(f'Plex Curator backend listening on {args.host}:{args.port} (open in browser at http://<this-computer-ip>:{args.port})')
    if args.host not in ('127.0.0.1','localhost','::1'):
        print('WARNING: No app login. Anyone who can reach this port may control Plex Curator. Restrict access to a trusted LAN/VPN; do not expose it to the internet.',flush=True)
    print(f'{len(LIB.rows)} records loaded; Plex token: {"found" if plex_token() else "not found"}; renames: {"enabled" if MEDIA_ROOTS else "disabled"}',flush=True)
    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
if __name__=='__main__':main()
