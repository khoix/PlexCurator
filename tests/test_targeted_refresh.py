"""Targeted live Plex refresh and efficient transactional database reads."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'backend'))
import engine,server,remote_bridge


def movie():
    return engine.normal_item({'plex_id':'9001','plex_title':'The Witch','type':'Movie','year':'2016',
       'guid':'plex://movie/a','file_path':'/media/Movies/The Witch (2016)/The Witch (2016).mkv'})

class TargetedRefreshTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.patch_state=patch.object(server,'STATE',Path(tmp.name));self.patch_state.start();self.addCleanup(self.patch_state.stop)
        lib=server.Library();lib.decisions={};lib.load([movie()],'SSH: test')
        self.patch_lib=patch.object(server,'LIB',lib);self.patch_lib.start();self.addCleanup(self.patch_lib.stop)

    def test_unchanged_live_record_retains_approval_and_unreturned_fields(self):
        server.LIB.set_decision('9001',{'title':'The Witch: A New England Folktale'})
        server.LIB.set_decision('9001',{'approved':True})
        with patch.object(server,'plex_metadata',return_value={'title':'The Witch','year':2016,'guid':'plex://movie/a'}):
            outcome=server.refresh_live_item('9001')
        self.assertFalse(outcome['changed_fields'])
        self.assertFalse(outcome['proposal_invalidated'])
        self.assertTrue(server.LIB.decisions['9001']['approved'])
        self.assertEqual(outcome['item']['file_path'],movie()['file_path'])

    def test_changed_live_metadata_invalidates_stale_approval(self):
        server.LIB.set_decision('9001',{'year':'2015'})
        server.LIB.set_decision('9001',{'approved':True})
        metadata={'title':'The VVitch','year':2015,'guid':'plex://movie/a',
                  'Media':[{'Part':[{'file':'/media/Movies/The Witch (2015)/The Witch (2015).mkv'}]}]}
        with patch.object(server,'plex_metadata',return_value=metadata):
            outcome=server.refresh_live_item('9001')
        self.assertTrue(outcome['proposal_invalidated'])
        self.assertEqual(outcome['item']['plex_title'],'The VVitch')
        self.assertEqual(outcome['item']['year'],'2015')
        self.assertIn('file_path',outcome['changed_fields'])
        self.assertNotIn('9001',server.LIB.decisions)

    def test_provider_punctuation_only_does_not_stage(self):
        item=engine.normal_item({'plex_id':'42','type':'Episode','plex_title':'To You, in 2000 Years: The Fall of Shiganshina (1)'})
        proposed,why=server.verify_provider_batch(item,'title',{'title':'To You, in 2000 Years - The Fall of Shiganshina (1)','year':'2013'})
        self.assertFalse(proposed)
        self.assertIn('punctuation',why)
        # Whitespace inside a word is substantive, not punctuation-only.
        item['plex_title']='Goose Bumps'
        proposed,_=server.verify_provider_batch(item,'title',{'title':'Goosebumps','year':'2015'})
        self.assertEqual(proposed,'Goosebumps')

class FastReadTests(unittest.TestCase):
    def test_remote_readonly_transaction_uses_no_full_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'plex.db'
            con=sqlite3.connect(path)
            con.executescript('''CREATE TABLE metadata_items (id INTEGER,metadata_type INTEGER,library_section_id INTEGER,parent_id INTEGER,title TEXT,original_title TEXT,year INTEGER,guid TEXT,user_thumb_url TEXT,summary TEXT,"index" INTEGER,deleted_at TEXT);
                CREATE TABLE library_sections(id INTEGER,name TEXT);
                CREATE TABLE media_items(id INTEGER,metadata_item_id INTEGER);
                CREATE TABLE media_parts(id INTEGER,media_item_id INTEGER,file TEXT);
                INSERT INTO library_sections VALUES(1,'Movies');
                INSERT INTO metadata_items VALUES(15,1,1,NULL,'Movie',NULL,2001,'plex://movie/15',NULL,'test',NULL,NULL);
                INSERT INTO media_items VALUES(8,15);
                INSERT INTO media_parts VALUES(9,8,'/media/Movies/Movie (2001).mkv');''')
            con.close()
            with patch.object(remote_bridge.sqlite3,'connect',wraps=sqlite3.connect) as connect:
                result=remote_bridge.perform({'op':'refresh','db':str(path)})
            self.assertEqual(result['rows'][0]['plex_id'],15)
            self.assertEqual(connect.call_count,1,'No in-memory database should be created')
            self.assertEqual(result['rows'][0]['file_path'],'/media/Movies/Movie (2001).mkv')
            rows=engine.import_db(path,copy_first=False)
            self.assertEqual(rows[0]['plex_title'],'Movie')

if __name__=='__main__':unittest.main()
