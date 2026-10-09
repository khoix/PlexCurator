"""Folder safety and full movie/series rename integration tests, no Plex writes."""
import json
import sqlite3
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import remote_bridge
import server
from engine import derive_show_folders, folder_proposal


class TestFolderBridge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'Movies'
        self.root.mkdir()
        self.movie = self.root / 'The Matrix (1998)'
        self.movie.mkdir()
        self.file = self.movie / 'The Matrix (1998).mkv'
        self.file.write_bytes(b'movie')
        (self.movie / 'subtitles.srt').write_text('subtitles')
        self.args = {'source':str(self.file), 'folder_source':str(self.movie),
                     'new_name':'The Matrix (1999).mkv','new_folder':'The Matrix (1999)',
                     'roots':[str(self.root)]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_preview_does_not_write(self):
        r=remote_bridge.folder_and_file_rename(self.args, False)
        self.assertFalse(r['applied'])
        self.assertEqual(r['new_folder'],str(self.root / 'The Matrix (1999)'))
        self.assertEqual(r['scan_folder'],str(self.root))
        self.assertTrue(self.file.exists())
        self.assertFalse((self.root / 'The Matrix (1999)').exists())

    def test_combined_rename_preserves_media_subtitles(self):
        r=remote_bridge.folder_and_file_rename(self.args, True)
        self.assertTrue(r['applied'])
        self.assertFalse(self.movie.exists())
        self.assertEqual(Path(r['new_file']).read_bytes(), b'movie')
        self.assertEqual((self.root/'The Matrix (1999)'/'subtitles.srt').read_text(),'subtitles')
        self.assertEqual(r['method'],'atomic-file-and-folder-rename')

    def test_folder_only_renames_all_contents(self):
        args = {**self.args,'new_name':''}
        r=remote_bridge.folder_and_file_rename(args, True)
        self.assertEqual(Path(r['new_file']).name, 'The Matrix (1998).mkv')
        self.assertEqual((self.root/'The Matrix (1999)'/'subtitles.srt').read_text(),'subtitles')

    def test_collision_does_not_touch_files(self):
        (self.root/'The Matrix (1999)').mkdir()
        with self.assertRaisesRegex(ValueError,'already exists'):
            remote_bridge.folder_and_file_rename(self.args,True)
        self.assertTrue(self.file.exists())
        self.assertEqual((self.movie/'subtitles.srt').read_text(),'subtitles')

    def test_roots_and_traversal_rejected(self):
        with self.assertRaisesRegex(ValueError,'BELOW an allowed media root'):
            remote_bridge.folder_and_file_rename({**self.args,'folder_source':str(self.root),'source':'','new_name':''},False)
        for unsafe in ('../escape','other/folder','..', '.', 'unsafe\\name'):
            with self.subTest(unsafe=unsafe), self.assertRaisesRegex(ValueError,'folder'):
                remote_bridge.folder_and_file_rename({**self.args,'new_folder':unsafe},False)
        other_root=Path(self.tmp.name)/'Other';other_root.mkdir()
        with self.assertRaisesRegex(ValueError,'BELOW an allowed media root'):
            remote_bridge.folder_and_file_rename({**self.args,'roots':[str(other_root)]},False)

    def test_failed_folder_move_rolls_back_filename(self):
        from unittest.mock import patch
        real=remote_bridge.media_rename
        # Simulate a race: destination folder created between preflight and renameat2.
        def renamed(*a,**k):
            result=real(*a,**k)
            if len(a)>1 and a[1] and a[0].get('new_name')=='The Matrix (1999).mkv':
                (self.root/'The Matrix (1999)').mkdir()
            return result
        with patch.object(remote_bridge,'media_rename',side_effect=renamed):
            with self.assertRaises(OSError):
                remote_bridge.folder_and_file_rename(self.args,True)
        self.assertTrue(self.file.exists())
        self.assertFalse((self.movie/'The Matrix (1999).mkv').exists())


class TestFolderLibrary(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)/'Series';self.root.mkdir()
        self.showdir=self.root/'Example Show';self.showdir.mkdir()
        self.season=self.showdir/'Season 1';self.season.mkdir()
        self.episodes=[]
        for i in range(1,3):
            ep=self.season/f'Example Show - S01E{i:02d}.mkv';ep.write_bytes(b'episode')
            self.episodes.append(ep)
        self.old_lib=server.LIB;self.old_state=server.STATE;self.old_roots=server.MEDIA_ROOTS
        server.STATE=Path(self.temp.name)
        server.MEDIA_ROOTS=[self.root]
        server.LIB=server.Library()
        show={'plex_id':'42','type':'Show','plex_title':'Example Show','year':'2021','guid':'plex://show/42',
              'file_path':'','folder_path':'','series_id':'42','library_section_id':'7'}
        eps=[{'plex_id':str(50+i),'type':'Episode','series_title':'Example Show','plex_title':'Episode',
              'file_path':str(ep),'series_id':'42', 'guid':f'plex://episode/{i}', 'year':'2021'} for i,ep in enumerate(self.episodes)]
        server.LIB.load([show]+eps,'Plex SQLite (read-only snapshot)')

    def tearDown(self):
        server.LIB=self.old_lib;server.STATE=self.old_state;server.MEDIA_ROOTS=self.old_roots
        self.temp.cleanup()

    def test_show_folder_derived_by_parent_id_not_title(self):
        self.assertEqual(server.LIB.rows['42']['folder_path'],str(self.showdir))
        self.assertEqual(folder_proposal(server.LIB.rows['42']), 'Example Show (2021)')

    def test_show_folder_rename_updates_episode_paths_and_can_scan(self):
        server.LIB.set_decision('42',{'folder':'Example Show (2021)'})
        server.LIB.set_decision('42',{'approved':True})
        with patch.object(server,'plex_metadata',return_value={'title':'Example Show','guid':'plex://show/42','year':'2021'}):
            result=server.apply_one('42')
        self.assertIn('folder',result['changes'])
        self.assertFalse(self.showdir.exists())
        newdir=self.root/'Example Show (2021)'
        self.assertEqual(server.LIB.rows['42']['folder_path'],str(newdir))
        self.assertEqual(server.LIB.rows['50']['file_path'],str(newdir/'Season 1'/self.episodes[0].name))
        self.assertTrue(Path(server.LIB.rows['51']['file_path']).exists())
        self.assertEqual(result['scan_path'],str(newdir))
        with patch.object(server,'plex_request') as plex_api:
            scans=server.scan_confirmed_renames([{'id':'42','new_file':str(newdir)}])
        self.assertEqual(scans['queued_folders'],1)
        plex_api.assert_called_once_with('POST','/library/sections/7/refresh',{'path':str(self.root)})

    def test_folder_ownership_rejects_unrelated_media(self):
        outsider=self.showdir/'Another Movie.mkv';outsider.write_bytes(b'bad')
        server.LIB.rows['99']={'plex_id':'99','type':'Movie','file_path':str(outsider)}
        with self.assertRaisesRegex(ValueError,'unrelated Plex'):
            server.preview_media_operation('42', '', 'Example Show (2021)')
        self.assertTrue(outsider.exists())

    def test_plex_sql_identifies_show_folder_from_episode_parentage(self):
        db=Path(self.temp.name)/'Plex library.db'
        conn=sqlite3.connect(db)
        conn.executescript('''
            CREATE TABLE metadata_items(id INTEGER,metadata_type INTEGER,library_section_id INTEGER,parent_id INTEGER,title TEXT,original_title TEXT,year INTEGER,guid TEXT,user_thumb_url TEXT,summary TEXT,"index" INTEGER,deleted_at TEXT);
            CREATE TABLE library_sections(id INTEGER,name TEXT);
            CREATE TABLE media_items(id INTEGER,metadata_item_id INTEGER);
            CREATE TABLE media_parts(id INTEGER,media_item_id INTEGER,file TEXT);
            INSERT INTO library_sections VALUES (7,'TV');
            INSERT INTO metadata_items VALUES (42,2,7,NULL,'Example Show','',2021,'plex://show/42',NULL,'',NULL,NULL);
            INSERT INTO metadata_items VALUES (43,3,7,42,'Season 1','',NULL,NULL,NULL,'',1,NULL);
            INSERT INTO metadata_items VALUES (50,4,7,43,'First Episode','',2021,'plex://episode/50',NULL,'',1,NULL);
            INSERT INTO media_items VALUES (51,50);
        ''')
        conn.execute('INSERT INTO media_parts VALUES (?,?,?)',(52,51,str(self.episodes[0])))
        conn.commit();conn.close()
        from engine import import_db
        for reader in (remote_bridge.rows_from_db, import_db):
            rows=reader(str(db))
            self.assertEqual(next(r for r in rows if str(r['plex_id'])=='50')['series_id'],42 if reader==remote_bridge.rows_from_db else '42')
            server.LIB.load(rows,'Plex SQLite (read-only snapshot)')
            self.assertEqual(server.LIB.rows['42']['folder_path'],str(self.showdir))

    def test_cannot_rename_an_episode_folder(self):
        with self.assertRaisesRegex(ValueError,'only available'):
            server.assert_folder_ownership('50',str(self.season))


if __name__=='__main__':unittest.main()
