"""Provider-backed title and filename verification, approval safety."""
import sys, unittest, tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'backend'))
import engine, server

def movie(pid=700,title='Goose Bumps',year='2016',file_title='Goose Bumps',file_year='2015',collections=''):
 return engine.normal_item({'plex_id':str(pid),'type':'Movie','plex_title':title,
  'year':year,'guid':f'plex://movie/{pid}','collections':collections,
  'file_path':f'/media/Movies/{file_title} ({file_year})/{file_title} ({file_year}).mkv'})

def choice(title,year,provider='TMDB'):
 return {'title':title,'year':year,'provider':provider,'source_url':f'https://example.org/{provider}','score':.98}

class SelectionTests(unittest.TestCase):
 def test_selects_matching_movie_provider(self):
  selected,err=server.select_provider_media(movie(),[choice('Goosebumps','2015')])
  self.assertEqual(selected['title'],'Goosebumps'); self.assertFalse(err)
 def test_conflicting_remakes_blocked(self):
  selected,err=server.select_provider_media(movie(title='Carrie',file_title='Carrie'),[choice('Carrie','1976'),choice('Carrie','2013')])
  self.assertIsNone(selected);self.assertIn('different years',err)
 def test_provider_disagreement_skips(self):
  selected,err=server.select_provider_media(movie(),[choice('Goosebumps','2015'),choice('Goosebumps','2016','Wikidata')])
  self.assertIsNone(selected);self.assertIn('different years',err)
 def test_wrong_plex_title_can_use_good_file_name(self):
  row=movie(title='This is an Ozlem Encode',file_title='This Is the End',file_year='2013')
  selected,err=server.select_provider_media(row,[choice('This Is the End','2013')])
  self.assertEqual(selected['title'],'This Is the End');self.assertFalse(err)
 def test_collection_prefix_untouched(self):
  row=movie(title='Star Wars: The Empire Strikes Back',file_title='The Empire Strikes Back',file_year='1980',collections='Star Wars')
  selected,_=server.select_provider_media(row,[choice('The Empire Strikes Back','1980')])
  fix,reason=server.verify_provider_batch(row,'title',selected)
  self.assertFalse(fix);self.assertIn('matches',reason)
 def test_collection_filename_reuses_prefix(self):
  row=movie(title='Star Wars: The Empire Strikes Back',file_title='The Empire Strikes Back',file_year='1981',collections='Star Wars')
  selected,_=server.select_provider_media(row,[choice('The Empire Strikes Back','1980')])
  fix,_=server.verify_provider_batch(row,'filename',selected)
  self.assertEqual(fix,'Star Wars: The Empire Strikes Back (1980).mkv')
 def test_movie_filename_uses_provider_year_not_plex(self):
  row=movie(year='2016',file_year='2016')
  selected,_=server.select_provider_media(row,[choice('Goosebumps','2015')])
  fix,_=server.verify_provider_batch(row,'filename',selected)
  self.assertEqual(fix,'Goosebumps (2015).mkv')
 def test_show_filename_skipped(self):
  row=engine.normal_item({'plex_id':'9','type':'Show','plex_title':'Severance','year':'2022'})
  fix,reason=server.verify_provider_batch(row,'filename',{'title':'Severance','year':'2022'})
  self.assertFalse(fix);self.assertIn('no media filename',reason)
 def test_episodic_filename_preserves_season_number(self):
  row=engine.normal_item({'plex_id':'9','type':'Episode','series_title':'She-Hulk: Attorney at Law','plex_title':'Old Title',
       'season_number':'1','episode_number':'2','file_path':'/series/She-Hulk/Season 1/Show.S01E02.Old.Title.mkv'})
  fix,reason=server.verify_provider_batch(row,'filename',{'title':'The Retreat','year':'2022'})
  self.assertTrue('S01E02' in fix);self.assertTrue('The Retreat' in fix);self.assertFalse(reason)
 def test_episode_without_number_no_confident_match(self):
  row=engine.normal_item({'type':'Episode','plex_title':'Episode Name','series_title':'Show','file_path':'/tv/show/unknown.mkv'})
  picked,_=server.select_provider_media(row,[choice('Episode Name','2020','TVmaze aired order')])
  self.assertIsNone(picked)

class StagingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  p=patch.object(server,'STATE',Path(self.tmp.name));p.start();self.addCleanup(p.stop)
  self.lib=server.Library();self.lib.decisions={};self.lib.load([movie()],'SSH: test')
 def test_title_stage_requires_approval_and_proposals_visibility(self):
  with patch.object(server,'batch_provider_candidates',return_value=([choice('Goosebumps','2015')],[])):
   report=self.lib.stage_metadata(['700'],'title')
  self.assertEqual(report['staged'][0]['proposed'],'Goosebumps')
  self.assertFalse(self.lib.decisions['700']['approved'])
  self.assertEqual(self.lib.listing({'type':['proposals'],'q':[''],'flagged':['false']})['total'],1)
  self.assertEqual(self.lib.decisions['700']['provider_sources'][0]['provider'],'TMDB')
  self.assertEqual(self.lib.rows['700']['plex_title'],'Goose Bumps')
 def test_filename_stages_independently_of_title(self):
  with patch.object(server,'batch_provider_candidates',return_value=([choice('Goosebumps','2015')],[])):
   report=self.lib.stage_metadata(['700'],'filename')
  self.assertEqual(report['staged'][0]['proposed'],'Goosebumps (2015).mkv')
  self.assertFalse(self.lib.decisions['700']['title'])
  self.assertTrue(self.lib.decisions['700']['filename'])
 def test_existing_user_changes_not_overwritten(self):
  self.lib.set_decision('700',{'title':'User-chosen title'})
  with patch.object(server,'batch_provider_candidates',return_value=([choice('Goosebumps','2015')],[])):
   report=self.lib.stage_metadata(['700'],'title')
  self.assertFalse(report['staged']);self.assertEqual(self.lib.decisions['700']['title'],'User-chosen title')
 def test_duplicate_batch_is_not_reapproved(self):
  with patch.object(server,'batch_provider_candidates',return_value=([choice('Goosebumps','2015')],[])):
   self.lib.stage_metadata(['700'],'filename')
   follow=self.lib.stage_metadata(['700'],'filename')
  self.assertFalse(follow['staged'])
 def test_provider_error_causes_skip_not_filename_guess(self):
  with patch.object(server,'batch_provider_candidates',return_value=([],['Wikidata: HTTP 429'])):
   report=self.lib.stage_metadata(['700'],'filename')
  self.assertFalse(report['staged']);self.assertEqual(self.lib.listing({'type':['proposals'],'q':[''],'flagged':['false']})['total'],0)
 def test_prior_approval_respected(self):
  self.lib.set_decision('700',{'title':'User title'});self.lib.set_decision('700',{'approved':True})
  with patch.object(server,'batch_provider_candidates') as lookup:
   result=self.lib.stage_metadata(['700'],'title')
  self.assertFalse(result['staged']);lookup.assert_not_called()
 def test_invalid_operation(self):
  with self.assertRaises(ValueError):self.lib.stage_metadata(['700'],'poster')

if __name__=='__main__': unittest.main()
