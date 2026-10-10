"""Explicit provider-preview consent and proposal-removal safety checks."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'backend'))
import engine,server

def movie(pid='500'):
    return engine.normal_item({'plex_id':pid,'type':'Movie','plex_title':'The Witch','year':'2016',
      'guid':'plex://movie/'+pid,'file_path':'/media/Movies/The Witch (2016)/The Witch (2016).mkv'})

def provider():
    return {'provider':'TMDB','title':'The Witch','year':'2015',
      'source_url':'https://example.org/movie','score':1.0}

class ProposalConsentTests(unittest.TestCase):
    def setUp(self):
        td=tempfile.TemporaryDirectory();self.addCleanup(td.cleanup)
        state=patch.object(server,'STATE',Path(td.name));state.start();self.addCleanup(state.stop)
        self.lib=server.Library();self.lib.decisions={};self.lib.load([movie()],'SSH: test')

    def preview(self,kind='year'):
        with patch.object(server,'batch_provider_candidates',return_value=([provider()],[])):
            return self.lib.preview_verification(['500'],kind)

    def test_preview_has_no_persistent_side_effects(self):
        old=(server.STATE/'decisions.json').read_bytes()
        report=self.preview()
        self.assertTrue(report['proposed'])
        self.assertEqual(self.lib.decisions,{})
        self.assertEqual((server.STATE/'decisions.json').read_bytes(),old)
        self.assertEqual(self.lib.listing({'type':['proposals']})['total'],0)

    def test_discard_prevents_later_commit(self):
        report=self.preview()
        self.lib.discard_preview(report['preview_token'])
        with self.assertRaisesRegex(ValueError,'expired'):
            self.lib.commit_preview(report['preview_token'],['500'])
        self.assertEqual(self.lib.decisions,{})

    def test_explicit_commit_creates_unapproved_proposal(self):
        report=self.preview()
        r=self.lib.commit_preview(report['preview_token'],['500'])
        self.assertEqual(len(r['staged']),1)
        self.assertFalse(self.lib.decisions['500']['approved'])
        self.assertEqual(self.lib.decisions['500']['year'],'2015')
        self.assertEqual(self.lib.listing({'type':['proposals']})['total'],1)

    def test_removal_revokes_approval_and_does_not_touch_plex(self):
        self.lib.set_decision('500',{'year':'2015','approved':True})
        with patch.object(server,'plex_request') as request:
            r=self.lib.remove_proposals(['500'])
        request.assert_not_called()
        self.assertEqual(len(r['removed']),1)
        self.assertNotIn('500',self.lib.decisions)
        self.assertEqual(self.lib.rows['500']['year'],'2016')
        self.assertEqual(json.loads((server.STATE/'decisions.json').read_text()),{})

    def test_stale_preview_does_not_overwrite_proposal(self):
        report=self.preview()
        self.lib.set_decision('500',{'year':'2014'})
        result=self.lib.commit_preview(report['preview_token'],['500'])
        self.assertFalse(result['staged'])
        self.assertEqual(self.lib.decisions['500']['year'],'2014')

    def test_preview_not_reused_or_committed_to_unlisted_id(self):
        report=self.preview()
        with self.assertRaisesRegex(ValueError,'outside the preview'):
            self.lib.commit_preview(report['preview_token'],['999'])
        report=self.preview()
        self.lib.commit_preview(report['preview_token'],['500'])
        with self.assertRaisesRegex(ValueError,'expired'):
            self.lib.commit_preview(report['preview_token'],['500'])

    def test_refresh_invalidates_preview(self):
        report=self.preview()
        self.lib.load([movie()],'SSH: refreshed')
        with self.assertRaisesRegex(ValueError,'expired'):
            self.lib.commit_preview(report['preview_token'],['500'])

    def test_title_and_filename_preview_are_unpersisted(self):
        with patch.object(server,'batch_provider_candidates',return_value=([provider()],[])):
            report=self.lib.preview_verification(['500'],'filename')
        self.assertTrue(report['proposed'])
        self.assertFalse(self.lib.decisions)

if __name__=='__main__':
    unittest.main()
