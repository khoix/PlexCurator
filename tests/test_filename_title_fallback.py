"""Filename-derived fallback titles remain unverified and require explicit approval."""
import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'backend'))
import engine,server

def item(pid='501', title='Untitled', basename='Real Film (2018).mkv', directory='Wrong Directory'):
    return engine.normal_item({'plex_id':pid,'type':'Movie','plex_title':title,
        'year':'2018','guid':'plex://movie/'+pid,
        'file_path':f'/media/Movies/{directory}/{basename}'})

class FilenameFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        pt=patch.object(server,'STATE',Path(self.tmp.name));pt.start();self.addCleanup(pt.stop)
        self.library=server.Library();self.library.decisions={}

    def test_movie_uses_filename_not_folder(self):
        self.assertEqual(server.filename_title_fallback(item()),'Real Film')

    def test_episode_requires_number_and_name(self):
        ep=engine.normal_item({'type':'Episode','plex_title':'Untitled',
            'file_path':'/media/Series/S/Season 2/S.S02E03.The.Correct.Episode.mkv'})
        self.assertEqual(server.filename_title_fallback(ep),'The Correct Episode')
        ep['file_path']='/media/Series/S/Season 2/S.S02E03.mkv'
        self.assertEqual(server.filename_title_fallback(ep),'')
        ep['file_path']='/media/Series/S/Season 2/Unknown.mkv'
        self.assertEqual(server.filename_title_fallback(ep),'')

    def test_no_guess_for_generic_names(self):
        self.assertEqual(server.filename_title_fallback(item(basename='Untitled (2018).mkv')),'')
        self.assertEqual(server.filename_title_fallback(item(basename='sample.1080p.mkv')),'')

    def test_unreliable_provider_offers_unverified_fallback(self):
        self.library.load([item()], 'SSH: test')
        with patch.object(server,'batch_provider_candidates',return_value=([],['TMDB: HTTP 429'])):
            report=self.library.stage_metadata(['501'],'title',preview_only=True)
        self.assertEqual(report['staged'][0]['proposed'],'Real Film')
        self.assertEqual(report['staged'][0]['evidence'],'filename')
        self.assertEqual(report['staged'][0]['sources'],[])
        self.assertEqual(self.library.decisions,{})
        self.assertEqual(self.library.decorated('501')['diagnostic']['filename_title_suggestion'],'Real Film')

    def test_ambiguous_provider_does_not_become_falsely_verified(self):
        self.library.load([item()], 'SSH: test')
        options=[{'title':'Real Film','year':'1998','provider':'TMDB'},
                 {'title':'Real Film','year':'2018','provider':'TMDB'}]
        with patch.object(server,'batch_provider_candidates',return_value=(options,[])):
            report=self.library.stage_metadata(['501'],'title',preview_only=True)
        self.assertEqual(report['staged'][0]['evidence'],'filename')
        self.assertIn('different years',report['staged'][0]['lookup_reason'])

    def test_prefer_provider_if_confident(self):
        self.library.load([item()], 'SSH: test')
        matched={'title':'Real Film','year':'2018','provider':'TMDB','source_url':'https://example.org/movie/1'}
        with patch.object(server,'batch_provider_candidates',return_value=([matched],[])):
            report=self.library.stage_metadata(['501'],'title',preview_only=True)
        self.assertEqual(report['staged'][0]['evidence'],'provider')

    def test_workout_numbered_track_title(self):
        ep=engine.normal_item({'plex_id':'11178','type':'Episode','plex_title':'Untitled',
            'series_title':'Beachbody Com Shaun T Insanity Deluxe',
            'file_path':'/media/Series/Beachbody.com - Shaun T - Insanity Deluxe/10 - Max Cardio Conditioning.m4v',
            'guid':'local://11178'})
        self.assertEqual(engine.file_title(ep),'Max Cardio Conditioning')
        self.assertEqual(server.filename_title_fallback(ep),'Max Cardio Conditioning')
        self.library.load([ep],'SSH: test')
        with patch.object(server,'batch_provider_candidates',return_value=([],[])):
            review=self.library.stage_metadata(['11178'],'title',preview_only=True)
        self.assertEqual(review['staged'][0]['proposed'],'Max Cardio Conditioning')
        self.assertEqual(review['staged'][0]['evidence'],'filename')
        self.assertFalse(review['staged'][0]['approved'])
        self.assertEqual(review['staged'][0]['sources'],[])
        self.assertEqual(self.library.decisions,{})

    def test_numbered_track_must_have_non_generic_name(self):
        ep=engine.normal_item({'type':'Episode','plex_title':'Untitled',
            'file_path':'/media/Series/S/Season 1/10 - Untitled.m4v'})
        self.assertEqual(server.filename_title_fallback(ep),'')
        ep['file_path']='/media/Series/S/Season 1/10.m4v'
        self.assertEqual(server.filename_title_fallback(ep),'')
        ep['file_path']='/media/Series/S/Season 1/2016 - Actual Title.m4v'
        self.assertEqual(server.filename_title_fallback(ep),'')

    def test_no_filename_guess_for_shows(self):
        self.assertEqual(server.filename_title_fallback({'type':'Show','plex_title':'Show','file_path':''}),'')

    def test_preserves_collection_prefix(self):
        film=item(title='Star Wars: A Film',basename='A Film (1980).mkv')
        film['collections']='Star Wars'
        proposed,_=server.verify_provider_batch(film,'title',{'title':server.filename_title_fallback(film)})
        self.assertFalse(proposed)

if __name__=='__main__':unittest.main()
