"""The batch-year workflow must leave actionable, discoverable proposals."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))
import engine
import server


def record(pid, name, year):
    return engine.normal_item({'plex_id':str(pid),'type':'Movie',
        'plex_title':name,'year':year,'guid':f'plex://movie/{pid}',
        'file_path':f'/movies/{name} ({year})/{name} ({year}).mkv'})


class ProposalListingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patcher=patch.object(server,'STATE',Path(self.temp.name))
        self.patcher.start();self.addCleanup(self.patcher.stop)
        self.library=server.Library()
        self.library.decisions={}
        self.library.load([record(101,'Movie A','2001'),
                           record(102,'Movie B','2002'),
                           record(103,'Movie C','2003')],'test')

    def listing(self,kind='all',q='',flagged='true'):
        return self.library.listing({'type':[kind],'q':[q],
            'flagged':[flagged],'offset':['0'],'limit':['100']})

    def test_staged_proposal_visible_under_issues_only(self):
        self.library.set_decision('101',{'year':'2000'})
        result=self.listing()
        self.assertIn('101',[v['plex_id'] for v in result['items']])
        self.assertEqual(result['stats']['proposals'],1)
        self.assertFalse(self.library.decisions['101']['approved'])

    def test_proposals_view_includes_approved_and_unapproved(self):
        self.library.set_decision('101',{'year':'2000'})
        self.library.set_decision('102',{'filename':'new.mkv'})
        self.library.set_decision('102',{'approved':True})
        result=self.listing(kind='proposals')
        self.assertEqual({x['plex_id'] for x in result['items']},{'101','102'})
        self.assertEqual(result['stats']['proposals'],2)
        self.assertEqual(result['stats']['reviewed'],1)

    def test_exact_id_lookup_filters_to_proposal(self):
        self.library.set_decision('101',{'year':'2000'})
        self.library.set_decision('102',{'year':'2000'})
        self.assertEqual([x['plex_id'] for x in self.listing('proposals','#102')['items']],['102'])
        self.assertEqual(self.listing('proposals','#103')['items'],[])

    def test_no_proposals_safely_empty(self):
        result=self.listing(kind='proposals')
        self.assertEqual(result['total'],0)
        self.assertEqual(result['stats']['proposals'],0)


if __name__=='__main__':unittest.main()
