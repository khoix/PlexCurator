"""Regression checks for default SSH roots and media-row action layout."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent.parent

class MediaLayoutTests(unittest.TestCase):
    def test_default_media_roots_only_on_first_connection(self):
        for path in ('web/src/main.ts','web/dist/main.js'):
            text=(ROOT/path).read_text(encoding='utf-8')
            self.assertIn("c ? c.media_roots : ['/media/Movies'", text)
            self.assertIn("'/media/Series']", text)
            self.assertNotIn('placeholder="/mnt/media/Movies&#10;/mnt/media/TV"', text)
    def test_status_remove_and_chevron_get_separate_grid_cells(self):
        for path in ('web/src/style.css','web/dist/style.css'):
            css=(ROOT/path).read_text(encoding='utf-8')
            self.assertIn('.media-row > .issue-tag { grid-column: 5;',css)
            self.assertIn('.media-row > .proposal-removal {',css)
            self.assertIn('grid-column: 6;',css)
            self.assertIn('.media-row > .row-arrow { grid-column: 7; grid-row: 1;',css)
            self.assertIn('.media-row > .issue-tag { grid-column: 4; }',css)
            self.assertIn('.media-row > .proposal-removal { grid-column: 5; }',css)
            self.assertIn('.media-row > .row-arrow,',css)

if __name__=='__main__': unittest.main()
