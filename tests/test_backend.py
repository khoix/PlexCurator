import io, os, sqlite3, sys, tempfile, threading, unittest, urllib.request, json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'backend'))
import engine, server

CSV='''plex_id,type,library,series_title,plex_title,original_title,year,guid,poster_override,file_path,summary_excerpt
42,Movie,Movies,,Movie.2001.1080p.BluRay.x264-RARBG,,2001,plex://movie/a,,/media/Movies/Movie (2001)/Movie.2001.1080p.BluRay.mkv,Test movie
52,Episode,Series,Example Show,Episode 2,,2016,plex://episode/z,,/media/Series/Example Show/Season 1/Example Show - S01E02 - Second Episode.mkv,Second episode
62,TV Show,Series,,Example Show,,2016,plex://show/k,,,Series
'''
class FakePlex(BaseHTTPRequestHandler):
    title='Movie.2001.1080p.BluRay.x264-RARBG'
    year=2001
    def log_message(self,*args):pass
    def do_GET(self):
        if self.path.startswith('/library/metadata/42'):
            body=json.dumps({'MediaContainer':{'Metadata':[{'title':self.__class__.title,'guid':'plex://movie/a','year':self.__class__.year}]}}).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        else:self.send_error(404)
    def do_PUT(self):
        from urllib.parse import parse_qs,urlparse
        if self.path.startswith('/library/metadata/42'):
            params=parse_qs(urlparse(self.path).query)
            self.__class__.title=params.get('title.value',[self.title])[0]
            self.__class__.year=int(params.get('year.value',[self.year])[0])
            self.send_response(200);self.end_headers()
        else:self.send_error(404)

class TestEngine(unittest.TestCase):
    def test_import_and_types(self):
        records=engine.import_csv(CSV)
        self.assertEqual(len(records),3)
        self.assertEqual(records[2]['type'],'Show')
        self.assertIn('Release/codec tags in filename',engine.diagnose(records[0])['issues'])
    def test_episode_filename(self):
        records=engine.import_csv(CSV)
        self.assertEqual(engine.file_title(records[1]),'Second Episode')
        self.assertIn('Missing episode title',engine.diagnose(records[1])['issues'])
    def test_preserve_prefix(self):
        record=engine.normal_item({'plex_id':'10','type':'Movie','plex_title':'Star Wars: The Empire Strikes Back','year':'1980','file_path':'/media/Movies/The Empire Strikes Back (1980)/The Empire Strikes Back (1980).mkv'})
        self.assertNotIn('Movie title differs from library folder',engine.diagnose(record)['issues'])
        self.assertEqual(engine.diagnose(record)['proposed_title'],'')
    def test_dont_flag_episode_still(self):
        record=engine.normal_item({'plex_id':'10','type':'Episode','plex_title':'Sample','poster_override':'media://video/frame','file_path':'/media/S/S01E01 - Sample.mkv'})
        self.assertNotIn('Poster is a video frame (review)',engine.diagnose(record)['issues'])
    def test_year_evidence_requires_agreeing_folder_file(self):
        row=engine.normal_item({'plex_id':'10','type':'Movie','plex_title':'Star Wars: The Empire Strikes Back',
            'year':'1981','guid':'plex://movie/10',
            'file_path':'/movies/The Empire Strikes Back (1980)/The Empire Strikes Back (1980).mkv'})
        d=engine.diagnose(row)
        self.assertTrue(d['year_evidence']['batch_safe'])
        self.assertEqual(d['year_evidence']['proposed_year'],'1980')
        self.assertIn('Release year differs from media naming',d['issues'])
        row['file_path']='/movies/The Empire Strikes Back (1979)/The Empire Strikes Back (1980).mkv'
        d=engine.diagnose(row)
        self.assertFalse(d['year_evidence']['batch_safe'])
        self.assertEqual(d['year_evidence']['proposed_year'],'')
        self.assertIn('Folder and filename years conflict',d['issues'])
    def test_wrong_movie_never_batch_staged(self):
        row=engine.normal_item({'plex_id':'10','type':'Movie','plex_title':'Completely Different Film',
            'year':'2008','guid':'plex://movie/10',
            'file_path':'/movies/True Title (2007)/True Title (2007).mkv'})
        self.assertFalse(engine.year_evidence(row)['batch_safe'])
    def test_no_tmdb_year_filter(self):
        row=engine.normal_item({'type':'Movie','plex_title':'300','year':'2007','file_path':'/movies/300 (2006)/300 (2006).mkv'})
        with patch.object(engine,'json_get',return_value={'results':[]}) as get:
            engine.tmdb_lookup(row,'token')
            self.assertNotIn('year=',get.call_args.args[0])
    def test_invalid_csv(self):
        with self.assertRaises(ValueError):engine.import_csv('foo,bar\na,b\n')
    def test_database_readonly(self):
        with tempfile.TemporaryDirectory() as t:
            db=Path(t)/'library.db';con=sqlite3.connect(db)
            con.executescript('''CREATE TABLE metadata_items(id INTEGER,metadata_type INTEGER,library_section_id INTEGER,parent_id INTEGER,title TEXT,original_title TEXT,year INTEGER,guid TEXT,user_thumb_url TEXT,summary TEXT,"index" INTEGER,deleted_at TEXT);
            CREATE TABLE library_sections(id INTEGER,name TEXT);
            CREATE TABLE media_items(id INTEGER,metadata_item_id INTEGER);
            CREATE TABLE media_parts(id INTEGER,media_item_id INTEGER,file TEXT);
            CREATE TABLE tags(id INTEGER,tag_type INTEGER,tag TEXT);
            CREATE TABLE taggings(id INTEGER,metadata_item_id INTEGER,tag_id INTEGER);
            INSERT INTO tags VALUES(21,2,'Star Wars');INSERT INTO taggings VALUES(1,42,21);
            INSERT INTO library_sections VALUES(1,'Movies');
            INSERT INTO metadata_items VALUES(42,1,1,NULL,'Movie','',2001,'plex://movie/a','','Movie summary',NULL,NULL);
            INSERT INTO media_items VALUES(1,42); INSERT INTO media_parts VALUES(1,1,'/media/Movies/Movie (2001).mkv');''')
            con.commit();con.close()
            before=db.read_bytes();result=engine.import_db(str(db))
            self.assertEqual(len(result),1);self.assertEqual(result[0]['plex_id'],'42')
            self.assertEqual(result[0]['collections'],'Star Wars')
            self.assertEqual(db.read_bytes(),before)

class TestOperations(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.prevstate=server.STATE;self.prevlib=server.LIB;self.prevroots=server.MEDIA_ROOTS;self.prevurl=server.PLEX_URL
        server.STATE=Path(self.temp.name);server.LIB=server.Library()
        self.root=Path(self.temp.name)/'media';self.root.mkdir()
        self.file=self.root/'Movie.2001.1080p.BluRay.mkv';self.file.write_bytes(b'FAKE MEDIA')
        row=engine.normal_item({'plex_id':'42','type':'Movie','plex_title':'Movie.2001.1080p.BluRay.x264-RARBG','year':'2001','guid':'plex://movie/a','file_path':str(self.file),'library':'Movies'})
        server.LIB.load([row],'test')
        server.MEDIA_ROOTS=[self.root.resolve()]
        self.fake=ThreadingHTTPServer(('127.0.0.1',0),FakePlex)
        self.thread=threading.Thread(target=self.fake.serve_forever,daemon=True);self.thread.start()
        server.PLEX_URL='http://127.0.0.1:'+str(self.fake.server_address[1])
        self.env=patch.dict(os.environ,{'PLEX_TOKEN':'test'});self.env.start()
        FakePlex.title='Movie.2001.1080p.BluRay.x264-RARBG'
        FakePlex.year=2001
    def tearDown(self):
        self.fake.shutdown();self.fake.server_close();self.thread.join(timeout=2)
        self.env.stop();server.STATE=self.prevstate;server.LIB=self.prevlib;server.MEDIA_ROOTS=self.prevroots;server.PLEX_URL=self.prevurl;self.temp.cleanup()
    def test_cannot_apply_without_approval(self):
        server.LIB.set_decision('42',{'title':'Movie','filename':'Movie (2001).mkv'})
        with self.assertRaisesRegex(ValueError,'Not approved'):server.apply_one('42')
        self.assertTrue(self.file.exists());self.assertEqual(FakePlex.title,'Movie.2001.1080p.BluRay.x264-RARBG')
    def test_stale_approval_resets(self):
        server.LIB.set_decision('42',{'title':'Movie'})
        server.LIB.set_decision('42',{'approved':True})
        self.assertTrue(server.LIB.decisions['42']['approved'])
        server.LIB.set_decision('42',{'title':'Different Movie'})
        self.assertFalse(server.LIB.decisions['42']['approved'])
    def test_apply_and_journal(self):
        server.LIB.set_decision('42',{'title':'Movie','filename':'Movie (2001).mkv'})
        server.LIB.set_decision('42',{'approved':True})
        log=server.apply_one('42')
        self.assertEqual(log['changes'],['title','filename'])
        self.assertTrue((self.root/'Movie (2001).mkv').exists());self.assertEqual(FakePlex.title,'Movie')
        self.assertFalse(server.LIB.decisions.get('42',{}).get('approved',False))
        self.assertTrue((server.STATE/'changes.jsonl').exists())
    def test_filename_only_rename_and_preflight(self):
        # Even when a movie's metadata title is already correct, changing its
        # on-disk basename is a separate, supported proposal.
        server.LIB.set_decision('42', {'filename':'Movie (2001).mkv'})
        self.assertEqual(server.validate_local_rename(str(self.file),'Movie (2001).mkv')['applied'],False)
        server.LIB.set_decision('42', {'approved':True})
        log=server.apply_one('42')
        self.assertEqual(log['changes'],['filename'])
        self.assertIn(log['rename_method'],('atomic-rename','hardlink-fallback'))
        self.assertTrue((self.root/'Movie (2001).mkv').exists())
        self.assertFalse(self.file.exists())

    def test_clean_filename_can_have_year_replaced(self):
        record=engine.normal_item({'type':'Movie','plex_title':'Movie','year':'2001',
           'file_path':str(self.root/'Movie (2001).mkv')})
        suggestion=engine.filename_proposal(record,'Movie',year='1999',force=True)
        self.assertEqual(suggestion,'Movie (1999).mkv')
        self.assertEqual(engine.filename_proposal(record,'Movie',year='1999'),'Movie (1999).mkv')

    def test_year_only_apply_and_approval(self):
        server.LIB.set_decision('42',{'year':'2000'})
        self.assertFalse(server.LIB.decisions['42']['approved'])
        with self.assertRaisesRegex(ValueError,'Not approved'):server.apply_one('42')
        server.LIB.set_decision('42',{'approved':True})
        log=server.apply_one('42')
        self.assertEqual(log['changes'],['year'])
        self.assertEqual(log['old_year'],'2001')
        self.assertEqual(log['new_year'],'2000')
        self.assertEqual(FakePlex.year,2000)
        self.assertEqual(server.LIB.rows['42']['year'],'2000')
    def test_year_validation_stale_and_bulk_staging(self):
        for bad in ('200', 'garbage','1790','2099'):
            with self.assertRaisesRegex(ValueError,'Year must be'):
                server.LIB.set_decision('42',{'year':bad})
        row=engine.normal_item({'plex_id':'43','type':'Movie','plex_title':'Star Wars: The Empire Strikes Back','year':'1981',
            'guid':'plex://movie/10','file_path':'/movies/The Empire Strikes Back (1980)/The Empire Strikes Back (1980).mkv'})
        row2=engine.normal_item({'plex_id':'44','type':'Movie','plex_title':'Other','year':'1981',
            'guid':'plex://movie/11','file_path':'/movies/Other (1980)/Other (1979).mkv'})
        server.LIB.load([*server.LIB.rows.values(),row,row2],'test')
        server.LIB.set_decision('43',{'title':'Star Wars: Episode V - The Empire Strikes Back','approved':False})
        with patch.object(server,'batch_provider_candidates',side_effect=lambda row: (
            ([{'title':'The Empire Strikes Back','year':'1980','provider':'Wikidata',
               'source_url':'https://www.wikidata.org/wiki/Q1'}],[]) if row['plex_id']=='43' else ([],[]))):
            batch=server.LIB.stage_years(['43','44'])
        self.assertEqual([x['id'] for x in batch['staged']],['43'])
        self.assertEqual(len(batch['skipped']),1)
        self.assertFalse(server.LIB.decisions['43']['approved'])
        self.assertEqual(server.LIB.decisions['43']['title'],'Star Wars: Episode V - The Empire Strikes Back')
        self.assertEqual(server.LIB.decisions['43']['year'],'1980')
        server.LIB.set_decision('43',{'approved':True})
        server.LIB.set_decision('43',{'year':'1979'})
        self.assertFalse(server.LIB.decisions['43']['approved'])
    def test_path_traversal_and_collision(self):
        with self.assertRaises(ValueError):server.safe_path(str(self.file),'../evil.mkv')
        with self.assertRaises(ValueError):server.safe_path(str(self.file),'evil.mp4')
        other=self.root/'Other.mkv';other.write_bytes(b'yes')
        with self.assertRaises(ValueError):server.safe_path(str(self.file),'Other.mkv')

if __name__=='__main__':unittest.main()
