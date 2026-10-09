import base64
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'backend'))
import remote_bridge
from ssh_transport import SSHTransport


class TestRemoteBridge(unittest.TestCase):
    def test_sqlite_snapshot_and_remote_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / 'Plex library.db'
            connection = sqlite3.connect(db)
            connection.executescript('''
                CREATE TABLE metadata_items(id INTEGER,metadata_type INTEGER,library_section_id INTEGER,parent_id INTEGER,title TEXT,original_title TEXT,year INTEGER,guid TEXT,user_thumb_url TEXT,summary TEXT,"index" INTEGER,deleted_at TEXT);
                CREATE TABLE library_sections(id INTEGER,name TEXT);
                CREATE TABLE media_items(id INTEGER,metadata_item_id INTEGER);
                CREATE TABLE media_parts(id INTEGER,media_item_id INTEGER,file TEXT);
                CREATE TABLE tags(id INTEGER,tag_type INTEGER,tag TEXT);
                CREATE TABLE taggings(id INTEGER,metadata_item_id INTEGER,tag_id INTEGER);
                INSERT INTO library_sections VALUES (5,'Movies');
                INSERT INTO metadata_items VALUES (123,1,5,NULL,'Star Wars: The Empire Strikes Back','',1980,'plex://movie/m',NULL,'A film',NULL,NULL);
                INSERT INTO media_items VALUES (6,123);
                INSERT INTO media_parts VALUES (7,6,'/library/Empire Strikes Back.mkv');
                INSERT INTO tags VALUES (14,2,'Star Wars');
                INSERT INTO taggings VALUES (2,123,14);
            ''')
            connection.commit()
            connection.close()
            before = db.read_bytes()
            result = remote_bridge.rows_from_db(str(db))
            self.assertEqual(result[0]['collections'], 'Star Wars')
            self.assertEqual(result[0]['plex_title'], 'Star Wars: The Empire Strikes Back')
            encoded = base64.urlsafe_b64encode(json.dumps({'op': 'load', 'db': str(db)}).encode()).decode()
            proc = subprocess.run([sys.executable, str(Path(remote_bridge.__file__)), encoded], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)['result']['rows'][0]['plex_id'], 123)
            self.assertEqual(db.read_bytes(), before)

    def test_file_rename_guard_and_no_clobber(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'Movies'
            root.mkdir()
            src = root / 'Old Title.mkv'
            src.write_bytes(b'video')
            args = {'source': str(src), 'new_name': 'New Title.mkv', 'roots': [str(root)]}
            self.assertFalse(remote_bridge.media_rename(args, False)['applied'])
            self.assertTrue(src.exists())
            (root / 'New Title.mkv').write_bytes(b'existing')
            with self.assertRaisesRegex(ValueError, 'exists'):
                remote_bridge.media_rename(args, True)
            self.assertEqual(src.read_bytes(), b'video')
            (root / 'New Title.mkv').unlink()
            with self.assertRaisesRegex(ValueError, 'basename'):
                remote_bridge.media_rename({**args, 'new_name': '../Escape.mkv'}, True)
            with self.assertRaisesRegex(ValueError, 'extension'):
                remote_bridge.media_rename({**args, 'new_name': 'New Title.mp4'}, True)
            result = remote_bridge.media_rename(args, True)
            self.assertTrue(result['applied'])
            self.assertFalse(src.exists())
            self.assertEqual((root / 'New Title.mkv').read_bytes(), b'video')
            remote_bridge.media_rename({'source': result['new_file'], 'new_name': 'Old Title.mkv', 'roots':[str(root)]}, True)
            self.assertTrue(src.exists())

    def test_rename_does_not_require_hardlinks_on_linux(self):
        import platform
        from unittest.mock import patch
        if platform.system() != 'Linux':
            self.skipTest('renameat2 is Linux-specific')
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            old=folder/'file.mkv';old.write_bytes(b'video')
            from unittest.mock import patch
            with patch.object(remote_bridge.os, 'link', side_effect=OSError('hardlinks disabled')):
                outcome=remote_bridge.media_rename({'source':str(old), 'new_name':'new.mkv', 'roots':[temp]},True)
            self.assertEqual(outcome['method'],'atomic-rename')
            self.assertFalse(old.exists())
            self.assertEqual((folder/'new.mkv').read_bytes(),b'video')

    def test_remote_host_input_validation(self):
        good = {'host': '192.168.1.101', 'user': 'root', 'db': '/var/lib/plexmediaserver/Library/Application Support/db'}
        self.assertEqual(SSHTransport.validate(good)['port'], 22)
        for bad in ('-oProxyCommand=x', 'localhost;touch /tmp/pwned', 'bad\nhost', ''):
            with self.assertRaisesRegex(ValueError, 'hostname'):
                SSHTransport.validate({**good, 'host': bad})
        with self.assertRaisesRegex(ValueError, 'absolute'):
            SSHTransport.validate({**good, 'db': 'relative'})
        with self.assertRaisesRegex(ValueError, 'absolute'):
            SSHTransport.validate({**good, 'media_roots': ['relative']})


if __name__ == '__main__':
    unittest.main()
