"""Validate favicon branding and production asset content types."""
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent

class IconAssetTests(unittest.TestCase):
    def test_icon_files_present_and_nonempty(self):
        for directory in ('web/public','web/dist'):
            for filename in ('favicon.ico','favicon-16x16.png','favicon-32x32.png','apple-touch-icon.png'):
                with self.subTest(directory=directory,filename=filename):
                    self.assertGreater((ROOT/directory/filename).stat().st_size,64)
    def test_entry_points_link_all_icons(self):
        for index in ('web/index.html','web/dist/index.html'):
            html=(ROOT/index).read_text(encoding='utf-8')
            for filename in ('favicon.ico','favicon-16x16.png','favicon-32x32.png','apple-touch-icon.png'):
                self.assertIn('/'+filename,html)
    def test_correct_mime_mappings(self):
        from pathlib import Path
        code=(ROOT/'backend/server.py').read_text(encoding='utf-8')
        self.assertIn("'.png':'image/png'",code)
        self.assertIn("'.ico':'image/x-icon'",code)

if __name__=='__main__':
    unittest.main()
