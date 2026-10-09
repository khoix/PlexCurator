import base64, json, os, sys, tempfile, threading, urllib.parse, urllib.request, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'backend'))
import server,engine

GIF=base64.b64decode('R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=')
class SimulatedPlex(BaseHTTPRequestHandler):
    guid='plex://movie/old'
    selected='metadata://posters/first'
    options=['metadata://posters/first','metadata://posters/second']
    deny_selected=False
    fail_get_matches=False
    def log_message(self,*args):pass
    def send_body(self,body,kind='application/xml'):
        self.send_response(200)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(body)))
        self.end_headers();self.wfile.write(body)
    def do_GET(self):
        parsed=urllib.parse.urlparse(self.path);path=parsed.path
        if path=='/library/metadata/42/matches':
            if self.fail_get_matches:self.send_error(404);return
            xml=b'<MediaContainer size="1"><SearchResult name="Film" year="2001" guid="plex://movie/new"/></MediaContainer>'
            self.send_body(xml);return
        if path=='/library/metadata/42/posters':
            children=[]
            for n,key in enumerate(self.__class__.options):
                url=f'/library/metadata/42/file?url={urllib.parse.quote(key,safe="")}'
                children.append(f'<Photo provider="tmdb" thumb="{url.replace("&","&amp;")}" key="{url.replace("&","&amp;")}" ratingKey="{key}" selected="{int(key==self.__class__.selected)}"/>')
            self.send_body(('<MediaContainer size="2">'+''.join(children)+'</MediaContainer>').encode());return
        if path=='/library/metadata/42/file':
            self.send_body(GIF,'image/gif');return
        if path=='/library/metadata/42':
            self.send_body(json.dumps({'MediaContainer':{'Metadata':[{'title':'Film','year':2001,'guid':self.__class__.guid,'thumb':'/library/metadata/42/file?url=metadata%3A%2F%2Fposters%2Ffirst'}]}}).encode(),'application/json');return
        self.send_error(404)
    def do_PUT(self):
        parsed=urllib.parse.urlparse(self.path);path=parsed.path
        qs=urllib.parse.parse_qs(parsed.query)
        if path=='/library/metadata/42/matches':self.send_error(404);return
        if path=='/library/metadata/42/match':
            self.__class__.guid=qs['guid'][0];self.send_body(b'');return
        if path=='/library/metadata/42/poster':
            if not self.__class__.deny_selected:self.__class__.selected=qs['url'][0]
            self.send_body(b'');return
        if path=='/library/metadata/42':self.send_body(b'');return
        self.send_error(404)
    def do_POST(self):
        parsed=urllib.parse.urlparse(self.path)
        if parsed.path=='/library/metadata/42/posters':
            self.__class__.options.append('upload://posters/new')
            self.send_body(b'');return
        self.send_error(404)

class TestArtAndMatches(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.prevstate,self.prevlib,self.prevurl=server.STATE,server.LIB,server.PLEX_URL
        server.STATE=Path(self.temp.name);server.LIB=server.Library()
        self.row=engine.normal_item({'plex_id':'42','plex_title':'Film','year':'2001','type':'Movie','guid':'plex://movie/old','file_path':'/media/Film.mkv'})
        server.LIB.load([self.row],'test')
        SimulatedPlex.guid='plex://movie/old';SimulatedPlex.selected='metadata://posters/first';SimulatedPlex.options=['metadata://posters/first','metadata://posters/second'];SimulatedPlex.deny_selected=False;SimulatedPlex.fail_get_matches=False
        self.plex=ThreadingHTTPServer(('127.0.0.1',0),SimulatedPlex)
        self.plexthread=threading.Thread(target=self.plex.serve_forever,daemon=True);self.plexthread.start()
        server.PLEX_URL=f'http://127.0.0.1:{self.plex.server_address[1]}'
        self.env=patch.dict(os.environ,{'PLEX_TOKEN':'test'});self.env.start()
        self.app=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.appthread=threading.Thread(target=self.app.serve_forever,daemon=True);self.appthread.start()
    def tearDown(self):
        self.app.shutdown();self.app.server_close();self.appthread.join(1)
        self.plex.shutdown();self.plex.server_close();self.plexthread.join(1)
        self.env.stop()
        server.STATE=self.prevstate;server.LIB=self.prevlib;server.PLEX_URL=self.prevurl;self.temp.cleanup()
    def get(self,path):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.app.server_address[1]}{path}') as r:return r.headers, r.read()
    def test_matches_use_get_and_xml_searchresult(self):
        matches=server.plex_matches(42)
        self.assertEqual(matches[0]['guid'],'plex://movie/new')
        _,body=self.get('/api/plex-matches/42')
        self.assertEqual(json.loads(body)[0]['guid'],'plex://movie/new')
    def test_poster_options_xml_photo_and_authenticated_preview(self):
        posters=server.plex_posters(42)
        self.assertEqual(len(posters),2)
        self.assertTrue(posters[0]['selected']);self.assertFalse(posters[1]['selected'])
        _,response=self.get('/api/plex-posters/42')
        self.assertEqual(len(json.loads(response)),2)
        headers,preview=self.get('/api/poster-choice/42/1')
        self.assertEqual(headers['Content-Type'],'image/gif')
        self.assertEqual(preview,GIF)
        _,current=self.get('/api/poster/42')
        self.assertEqual(current,GIF)
    def test_apply_existing_poster_verifies_selected_and_records(self):
        server.LIB.set_decision('42',{'poster_key':'metadata://posters/second'})
        server.LIB.set_decision('42',{'approved':True})
        result=server.apply_one('42')
        self.assertEqual(result['changes'],['poster'])
        self.assertEqual(SimulatedPlex.selected,'metadata://posters/second')
    def test_poster_must_confirm_selection(self):
        SimulatedPlex.deny_selected=True
        server.LIB.set_decision('42',{'poster_key':'metadata://posters/second'})
        server.LIB.set_decision('42',{'approved':True})
        with self.assertRaisesRegex(ValueError,'did not confirm'):
            server.apply_one('42')
    def test_provider_upload_then_select(self):
        server.LIB.set_decision('42',{'poster_url':'https://image.tmdb.org/t/p/original/example.jpg'})
        server.LIB.set_decision('42',{'approved':True})
        log=server.apply_one('42')
        self.assertEqual(log['changes'],['poster_uploaded','poster_selected'])
        self.assertEqual(SimulatedPlex.selected,'upload://posters/new')
    def test_rematch_verifies_guid(self):
        server.LIB.set_decision('42',{'match_guid':'plex://movie/new'})
        server.LIB.set_decision('42',{'approved':True})
        log=server.apply_one('42')
        self.assertEqual(log['changes'],['rematch']);self.assertEqual(SimulatedPlex.guid,'plex://movie/new')
    def test_metadata_xml_video_parsing(self):
        with patch.object(server,'plex_request',return_value={'MediaContainer':{'Video':[{'title':'Film','guid':'plex://movie/old'}]}}):
            self.assertEqual(server.plex_metadata('42')['title'],'Film')
    def test_matches_fallback_only_on_404(self):
        original=server.plex_request
        calls=[]
        def mocked(method,path,params=None):
            if path.endswith('/matches'):
                calls.append(method)
                if method=='GET':raise ValueError('Plex API GET /library/metadata/42/matches: HTTP 404')
                return {'MediaContainer':{'SearchResult':[{'guid':'plex://movie/new'}]}}
            return original(method,path,params)
        with patch.object(server,'plex_request',side_effect=mocked):
            self.assertEqual(server.plex_matches(42)[0]['guid'],'plex://movie/new')
        self.assertEqual(calls,['GET','PUT'])
    def test_poster_proxy_cannot_fetch_other_host(self):
        with self.assertRaisesRegex(ValueError,'Invalid Plex image path'):
            server.plex_image('http://evil.local/library/metadata/42/file','42')
        with self.assertRaisesRegex(ValueError,'Invalid Plex image path'):
            server.plex_image('/library/metadata/43/file','42')
    def test_poster_sources_are_exclusive(self):
        server.LIB.set_decision('42',{'poster_url':'https://image.tmdb.org/a.jpg'})
        server.LIB.set_decision('42',{'poster_key':'metadata://posters/first'})
        self.assertEqual(server.LIB.decisions['42']['poster_url'],'')
        server.LIB.set_decision('42',{'poster_url':'https://image.tmdb.org/a.jpg'})
        self.assertEqual(server.LIB.decisions['42']['poster_key'],'')

if __name__=='__main__':unittest.main()
