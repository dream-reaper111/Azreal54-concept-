"""Exercise background command routing without binding a network socket."""
import copy
import json
import threading
import time
import unittest
from unittest.mock import patch
import admin
from lab import ACTORS


class Commands(unittest.TestCase):
    def setUp(self):
        self.app=admin.App(test_fixtures=True)
        self.addCleanup(self.app.close)

    def wait_job(self,identifier):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            with self.app.lock:
                row=copy.deepcopy(next(job for job in self.app.jobs if job['id']==identifier))
            if row['status']!='running':return row
            time.sleep(.01)
        self.fail('Command worker did not finish')

    def test_online_brief_runs_on_worker_and_preserves_results(self):
        calls=[]
        def collect(root):
            self.assertIsNot(threading.current_thread(),threading.main_thread())
            calls.append('collection');return {'retrieved':1,'fixture':True}
        def ask(app,mode,text,role):
            self.assertTrue(app.lock.acquire(timeout=.3),'SLM cannot reacquire app lock')
            app.lock.release();calls.append('slm');return {'text':'explicit fixture'}
        with patch('admin.collection.run',side_effect=collect),patch('admin.slm.ask',side_effect=ask):
            response=self.app.submit({'action':'online_brief','text':'Review the fixture','role':'poc_red'})
            job=self.wait_job(response['job_id'])
        self.assertEqual(job['status'],'completed',job)
        self.assertEqual(calls,['collection','slm'])
        self.assertEqual(job['result']['shared_slm_plan']['text'],'explicit fixture')
        self.assertFalse(job['result']['testing_permissions_changed'])

    def test_exploit_lookup_runs_once_and_never_uses_classifier(self):
        result={'records':[],'execution_performed':False,'fixture':True}
        with patch('admin.exploit_references.search',return_value=result) as lookup,patch.object(self.app.team,'review',side_effect=AssertionError('Wrong classifier fallback')):
            response=self.app.submit({'action':'published_exploits','text':'fixture'})
            job=self.wait_job(response['job_id'])
        self.assertEqual(job['status'],'completed',job)
        lookup.assert_called_once_with('fixture')
        self.assertEqual(job['result'],result)

    def test_online_brief_retains_collection_when_planning_fails(self):
        receipt={'retrieved':1,'quarantined':1,'fixture':True}
        with patch('admin.collection.run',return_value=receipt),patch('admin.slm.ask',side_effect=ValueError('fixture failure')):
            job=self.wait_job(self.app.submit({'action':'online_brief','text':'Review the fixture'})['job_id'])
        self.assertEqual(job['status'],'partial',job)
        self.assertEqual(job['result']['collection'],receipt)
        self.assertIsNone(job['result']['shared_slm_plan'])
        self.assertEqual(job['result']['planning_error']['type'],'ValueError')
        self.assertFalse(self.app.snapshot()['busy'])

    def test_empty_current_collection_never_claims_a_fresh_plan(self):
        receipt={'retrieved':0,'rejected':5,'fixture':True}
        with patch('admin.collection.run',return_value=receipt),patch('admin.slm.ask') as ask:
            job=self.wait_job(self.app.submit({'action':'online_brief','text':'Review current evidence'})['job_id'])
        ask.assert_not_called()
        self.assertEqual(job['status'],'partial',job)
        self.assertEqual(job['result']['planning_error']['type'],'NoCurrentEvidence')

    def test_shared_collection_cooldown_and_busy_state(self):
        started,release=threading.Event(),threading.Event()
        def collect(root):
            started.set();release.wait(2);return {'fixture':True}
        with patch('admin.collection.run',side_effect=collect):
            response=self.app.submit({'action':'collect_sources'})
            self.assertTrue(started.wait(1))
            try:
                self.assertTrue(self.app.snapshot()['busy'])
                with self.assertRaises(RuntimeError):self.app.submit({'action':'published_exploits','text':'fixture'})
            finally:release.set()
            self.assertEqual(self.wait_job(response['job_id'])['status'],'completed')
        for command in ({'action':'collect_sources'},{'action':'online_brief','text':'fixture'},{'action':'hak5_repos'}):
            with self.assertRaisesRegex(ValueError,'one per minute'):self.app.submit(command)

    def test_hak5_reference_metadata_reaches_every_role(self):
        rows=[{'name':'hak5/fixture','url':'https://github.com/hak5/fixture','retrieval_kind':'stored_snapshot','evidence_status':'quarantine','score':1}]
        with patch('lab.knowledge.lookup',return_value={'results':[]}),patch('lab.hak5_catalog.search',return_value=rows) as search:
            for role in ACTORS-{'controller'}:
                result=self.app.team.tools('fixture',role,reference_root=self.app.evidence.root.parent)
                self.assertEqual(result['repository_references'],rows)
        self.assertEqual(search.call_count,len(ACTORS)-1)
        self.assertEqual(self.app.team.bus.snapshot()[-2]['payload']['repository_references'],rows)

    def test_spread_model_uses_supplied_graph_and_no_training(self):
        inventory={'authorized':True,'nodes':[{'id':name,'label':name,'kind':'fixture'} for name in 'abc'],
                   'entry':'a','links':[{'source':'a','target':'b','status':'observed','evidence':'fixture observation'},
                                        {'source':'b','target':'c','status':'hypothesis','evidence':''}]}
        response=self.app.submit({'action':'spread_model','text':json.dumps({'inventory':inventory,'contained':['b'],'steps':3})})
        job=self.wait_job(response['job_id'])
        self.assertEqual(job['status'],'completed',job)
        self.assertEqual(job['result']['timeline'][-1]['red_reachable'],['a','b','c'])
        self.assertEqual(job['result']['timeline'][-1]['blue_reachable'],['a'])
        self.assertEqual(job['result']['outbound_requests'],0)

    def test_automatic_role_research_review_preserves_source_failure(self):
        receipt={'role':'web_red','requests':[{'provider':'github','status':'failed'}],'items':[]}
        review={'completion':'complete','status':'pending_admin_review'}
        with patch.object(self.app.role_research,'collect',return_value=receipt) as collect,patch.object(self.app.council,'review',return_value=review) as council:
            response=self.app.submit({'action':'role_hive_review','role':'web_red','text':'Review this explicit fixture'})
            job=self.wait_job(response['job_id'])
        self.assertEqual(job['status'],'partial')
        self.assertEqual(job['result']['research'],receipt)
        collect.assert_called_once_with('web_red')
        self.assertEqual(council.call_args.kwargs['research_receipt'],receipt)


if __name__=='__main__':unittest.main()
