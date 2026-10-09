"""The bulk-scan API only uses successful renames in the Curator journal."""
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'backend'))
import server


class TestBatchPartialScans(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.original_state=server.STATE
        server.STATE=Path(self.temp.name)
        self.records=[
            {'plex_id':'101','section_id':'2','changes':['filename'], 'new_file':'/media/Series/My Show/Season 1/E01.mkv'},
            {'plex_id':'102','section_id':'2','changes':['filename'], 'new_file':'/media/Series/My Show/Season 1/E02.mkv'},
            {'plex_id':'103','section_id':'2','changes':['filename'], 'new_file':'/media/Series/Other Show/Season 1/E03.mkv'},
            {'plex_id':'104','section_id':'3','changes':['filename'], 'new_file':'/media/Films/A Film/A Film.mkv'},
        ]
        (server.STATE/'changes.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in self.records),encoding='utf-8')

    def tearDown(self):
        server.STATE=self.original_state
        self.temp.cleanup()

    def req(self,i):
        r=self.records[i]
        return {'id':r['plex_id'],'new_file':r['new_file']}

    def test_two_files_same_folder_one_scan(self):
        calls=[]
        def fake(method,route,params):
            calls.append((method,route,params))
        with patch.object(server,'plex_request',side_effect=fake):
            result=server.scan_confirmed_renames([self.req(0),self.req(1),self.req(0)])
        self.assertEqual(result['requested_files'],2)
        self.assertEqual(result['unique_folders'],1)
        self.assertEqual(result['queued_folders'],1)
        self.assertEqual(calls,[('POST','/library/sections/2/refresh',{'path':'/media/Series/My Show/Season 1'})])
        self.assertEqual(result['results'][0]['ids'],['101','102'])
        self.assertIn('scan_requested',(server.STATE/'changes.jsonl').read_text())

    def test_scans_only_distinct_folders_and_sections(self):
        with patch.object(server,'plex_request') as api:
            result=server.scan_confirmed_renames([self.req(i) for i in range(4)])
        self.assertEqual(result['unique_folders'],3)
        self.assertEqual(api.call_count,3)
        self.assertEqual(result['failed_folders'],0)

    def test_failed_scans_are_reported_without_retrying_successful_folders(self):
        def api(method,route,params):
            if 'Other Show' in params['path']:
                raise ValueError('Plex API returned HTTP 503')
        with patch.object(server,'plex_request',side_effect=api):
            result=server.scan_confirmed_renames([self.req(0),self.req(2)])
        self.assertEqual(result['queued_folders'],1)
        self.assertEqual(result['failed_folders'],1)
        self.assertIn('503',result['results'][1]['error'])

    def test_unconfirmed_path_rejected_before_any_scan(self):
        with patch.object(server,'plex_request') as api:
            with self.assertRaisesRegex(ValueError,'not confirmed'):
                server.scan_confirmed_renames([self.req(0),{'id':'102','new_file':'/media/Series/Evil.mkv'}])
            api.assert_not_called()

    def test_failed_journal_entry_rejected(self):
        with (server.STATE/'changes.jsonl').open('a') as log:
            log.write(json.dumps({'plex_id':'108','status':'failed','changes':['filename'],
                'new_file':'/media/Series/suspicious.mkv','section_id':'8'})+'\n')
        with self.assertRaisesRegex(ValueError,'not confirmed'):
            server.scan_confirmed_renames([{'id':'108','new_file':'/media/Series/suspicious.mkv'}])

    def test_post_api_bulk_scans(self):
        httpd=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        thread=threading.Thread(target=httpd.serve_forever,daemon=True)
        thread.start()
        try:
            url=f'http://127.0.0.1:{httpd.server_address[1]}/api/scan-renames'
            data=json.dumps({'renames':[self.req(0),self.req(1),self.req(2)]}).encode()
            request=urllib.request.Request(url,data=data,method='POST',
                headers={'Content-Type':'application/json'})
            with patch.object(server,'plex_request') as api:
                with urllib.request.urlopen(request,timeout=5) as response:
                    payload=json.load(response)
            self.assertEqual(payload['requested_files'],3)
            self.assertEqual(payload['queued_folders'],2)
            self.assertEqual(api.call_count,2)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_invalid_and_missing_library_section(self):
        with self.assertRaisesRegex(ValueError,'between 1 and 500'):
            server.scan_confirmed_renames([])
        with self.assertRaisesRegex(ValueError,'Invalid Plex ID'):
            server.scan_confirmed_renames([{'id':'bad','new_file':'/media/Film.mkv'}])
        with (server.STATE/'changes.jsonl').open('a') as log:
            log.write(json.dumps({'plex_id':'109','changes':['filename'],
                'new_file':'/media/Film.mkv','section_id':''})+'\n')
        with self.assertRaisesRegex(ValueError,'missing library section'):
            server.scan_confirmed_renames([{'id':'109','new_file':'/media/Film.mkv'}])

if __name__=='__main__':unittest.main()
