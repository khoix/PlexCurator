"""Tests for provider-led release year proposals (no external services)."""
import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import engine,server

def movie(title='The Witch',year='2016'):
    return engine.normal_item({'plex_id':'750','type':'Movie','plex_title':title,'year':year,
      'guid':'plex://movie/750','file_path':'/movies/The Witch (2015)/The Witch (2015).mkv'})

def choice(title='The Witch',year='2015',provider='TMDB'):
    return {'title':title,'year':year,'provider':provider,
      'source_url':'https://example.org/'+provider, 'score':.2}

class ProviderYears(unittest.TestCase):
    def test_provider_year_beats_folder_and_plex(self):
        selected,reason=server.select_provider_year(movie(),[choice()])
        self.assertEqual(selected['year'],'2015')
        self.assertFalse(reason)

    def test_conflicting_sources_skip(self):
        selected,reason=server.select_provider_year(movie(),[choice(),choice(year='2016',provider='Wikidata')])
        self.assertIsNone(selected)
        self.assertIn('disagree',reason)

    def test_same_title_remakes_skip(self):
        row=engine.normal_item({'type':'Movie','plex_title':'Carrie','year':'2000'})
        selected,reason=server.select_provider_year(row,[choice('Carrie','1976'),choice('Carrie','2013')])
        self.assertIsNone(selected)
        self.assertIn('different years',reason)

    def test_different_file_and_plex_titles_skip(self):
        row=movie('Totally Different Title')
        selected,reason=server.select_provider_year(row,[choice()])
        self.assertIsNone(selected)
        self.assertIn('disagree',reason)

    def test_staging_preserves_evidence_and_requires_approval(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(server,'STATE',Path(tmp)):
            lib=server.Library()
            lib.decisions={};lib.load([movie()],'test')
            with patch.object(server,'batch_provider_candidates',return_value=([choice()],[])):
                report=lib.stage_years(['750'])
            self.assertEqual(report['staged'][0]['new_year'],'2015')
            self.assertFalse(lib.decisions['750']['approved'])
            self.assertEqual(lib.decisions['750']['year_sources'][0]['provider'],'TMDB')
            lib.set_decision('750',{'approved':True})
            self.assertEqual(lib.decisions['750']['year_sources'][0]['year'],'2015')
            lib.set_decision('750',{'year':'2014'})
            self.assertFalse(lib.decisions['750']['approved'])
            self.assertEqual(lib.decisions['750']['year_sources'],[])

    def test_no_provider_lookup_does_not_stage_file_year(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(server,'STATE',Path(tmp)):
            lib=server.Library();lib.decisions={};lib.load([movie()],'test')
            with patch.object(server,'batch_provider_candidates',return_value=([],['offline'])):
                result=lib.stage_years(['750'])
            self.assertFalse(result['staged'])
            self.assertEqual(len(result['skipped']),1)

    def test_approved_proposal_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(server,'STATE',Path(tmp)):
            lib=server.Library();lib.decisions={};lib.load([movie()],'test')
            lib.set_decision('750',{'year':'2014'})
            lib.set_decision('750',{'approved':True})
            with patch.object(server,'batch_provider_candidates') as mock:
                report=lib.stage_years(['750'])
            mock.assert_not_called()
            self.assertEqual(lib.decisions['750']['year'],'2014')
            self.assertFalse(report['staged'])

    def test_show_tvmaze_evidence(self):
        row=engine.normal_item({'type':'Show','plex_title':'Severance','year':'2023'})
        picked,_=server.select_provider_year(row,[choice('Severance','2022','TVmaze')])
        self.assertEqual(picked['year'],'2022')

if __name__=='__main__':unittest.main()
