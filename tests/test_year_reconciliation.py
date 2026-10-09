"""Metadata providers drive comparison of Plex year, filename, and folder."""
import sys,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'backend'))
import server,engine

def movie(id,plex='2013',folder='2014',filename='2014',title='Blue Ruin'):
    return engine.normal_item({'plex_id':str(id),'type':'Movie','plex_title':title,'year':plex,
        'guid':f'plex://movie/{id}',
        'file_path':f'/media/Movies/{title} ({folder})/{title} ({filename}).mkv'})

def provider(year='2013',title='Blue Ruin'):
    return {'provider':'TMDB','title':title,'year':year,'source_url':'https://www.themoviedb.org/movie/1','score':0.8}

class YearReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=patch.object(server,'STATE',Path(self.tmp.name));self.p.start()
        self.library=server.Library();self.library.decisions={}
    def tearDown(self):self.p.stop();self.tmp.cleanup()
    def stage(self,rows,year='2013',provider_title='Blue Ruin'):
        self.library.load(rows,'SSH: Plex read-only SQLite snapshot')
        with patch.object(server,'batch_provider_candidates',return_value=([provider(year,provider_title)],[])):
            return self.library.stage_years([str(r['plex_id']) for r in rows])

    def test_correct_plex_wrong_filename_and_folder(self):
        out=self.stage([movie(10)])
        r=out['staged'][0];self.assertEqual(r['title'],'Blue Ruin')
        self.assertEqual(r['plex_year'],'2013');self.assertEqual(r['filename_year'],'2014')
        self.assertEqual(r['folder_year'],'2014');self.assertEqual(r['provider_year'],'2013')
        self.assertEqual(set(r['changes']),{'filename','folder'})
        self.assertEqual(r['suggested']['filename'],'Blue Ruin (2013).mkv')
        self.assertEqual(r['suggested']['folder'],'Blue Ruin (2013)')
        self.assertEqual(self.library.decisions['10']['year'],'')
        self.assertFalse(self.library.decisions['10']['approved'])
        self.assertEqual(self.library.decisions['10']['year_sources'][0]['provider'],'TMDB')

    def test_wrong_plex_correct_files(self):
        out=self.stage([movie(11,plex='2014',folder='2013',filename='2013')])
        self.assertEqual(out['staged'][0]['changes'],['year'])
        self.assertEqual(self.library.decisions['11']['year'],'2013')

    def test_both_plex_and_file_wrong(self):
        out=self.stage([movie(12,plex='2015',folder='2014',filename='2014')])
        self.assertEqual(set(out['staged'][0]['changes']),{'year','filename','folder'})
        self.assertFalse(self.library.decisions['12']['approved'])

    def test_identical_provider_and_media_is_verified(self):
        out=self.stage([movie(13,plex='2013',folder='2013',filename='2013')])
        self.assertFalse(out['staged']);self.assertEqual(out['verified'][0]['title'],'Blue Ruin')

    def test_ambiguous_remake_skipped_with_title_and_sources(self):
        self.library.load([movie(14)],'SSH: Plex read-only SQLite snapshot')
        with patch.object(server,'batch_provider_candidates',return_value=([provider('2013'),provider('2014')],[])):
            out=self.library.stage_years(['14'])
        self.assertFalse(out['staged']);self.assertEqual(out['skipped'][0]['title'],'Blue Ruin')
        self.assertTrue(out['skipped'][0]['sources'])

    def test_collection_prefix_is_not_replaced(self):
        row=engine.normal_item({'plex_id':'15','type':'Movie','plex_title':'Star Wars: The Empire Strikes Back','year':'1981',
          'guid':'plex://movie/15','file_path':'/media/Movies/The Empire Strikes Back (1980)/The Empire Strikes Back (1980).mkv'})
        self.library.load([row],'SSH: Plex')
        with patch.object(server,'batch_provider_candidates',return_value=([provider('1980','The Empire Strikes Back')],[])):
            out=self.library.stage_years(['15'])
        self.assertEqual(out['staged'][0]['changes'],['year'])
        self.assertEqual(self.library.decisions['15']['title'],'')

    def test_conflicting_prior_proposal_not_overwritten(self):
        self.library.load([movie(16)],'SSH: Plex')
        self.library.set_decision('16',{'filename':'custom.mkv'})
        with patch.object(server,'batch_provider_candidates',return_value=([provider()],[])):
            out=self.library.stage_years(['16'])
        self.assertFalse(out['staged'])
        self.assertIn('conflicts',out['skipped'][0]['reason'])
        self.assertEqual(self.library.decisions['16']['filename'],'custom.mkv')

    def test_no_folder_year_does_not_invent_rename(self):
        row=movie(17);row['file_path']='/media/Movies/Unsorted/Blue Ruin (2014).mkv'
        out=self.stage([row]);self.assertEqual(out['staged'][0]['changes'],['filename'])

if __name__=='__main__':unittest.main()
