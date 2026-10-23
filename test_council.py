"""Mocked generation fixtures test protocol only, never council model quality."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from council import Council


class CouncilTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.council=Council(Path(self.tmp.name)/'reviews')
        self.roles=patch('council.known_roles',return_value={'analyst','defender','hephaestus','hydra','aegis'})
        self.roles.start();self.addCleanup(self.roles.stop)

    def test_three_shared_contexts_persist_then_decision_only(self):
        with patch('council.generate',side_effect=[{'text':'fixture planner'},{'text':'fixture critic'},{'text':'fixture chair'}]) as generate:
            report=self.council.review(object(),'Review fixture project','hydra')
        self.assertEqual(generate.call_count,3)
        self.assertEqual([p['role'] for p in report['participants']],['hydra','aegis','hephaestus'])
        self.assertEqual(report['status'],'pending_admin_review')
        self.assertFalse(report['provenance']['independent_models'])
        saved=self.council.get(report['id'])
        self.assertEqual(len(saved['passes']),3)
        self.assertEqual(len({p['request_id'] for p in saved['passes']}),3)
        self.assertIn('UNTRUSTED',generate.call_args.args[1])
        accepted=self.council.decide(report['id'],'accept','authenticated admin','Reviewed fixture proposal')
        self.assertEqual(accepted['status'],'accepted')
        for key in ('permissions_granted','changes_applied','training_occurred'):
            self.assertFalse(accepted[key])
        with self.assertRaises(ValueError):
            self.council.decide(report['id'],'accept','admin','second decision')
        self.assertEqual(self.council.snapshot()[0]['id'],report['id'])
        self.assertEqual((self.council.root/report['id']/'report.json').stat().st_mode&0o777,0o600)

    def test_partial_failure_retains_observed_outputs(self):
        with patch('council.generate',side_effect=[{'text':'observed fixture'},RuntimeError('not observed output')]) as generate:
            report=self.council.review(object(),'fixture objective','analyst')
        self.assertEqual(generate.call_count,2)
        self.assertEqual(report['completion'],'partial')
        self.assertEqual(report['status'],'pending_admin_review')
        saved=self.council.get(report['id'])
        self.assertEqual(saved['passes'][0]['text'],'observed fixture')
        self.assertEqual(len(saved['passes']),1)
        self.assertEqual(saved['error']['phase'],'critic')

    def test_interrupt_persists_partial_then_propagates(self):
        with patch('council.generate',side_effect=[{'text':'observed fixture'},KeyboardInterrupt()]):
            with self.assertRaises(KeyboardInterrupt):
                self.council.review(object(),'fixture objective','analyst')
        report=self.council.get(self.council.snapshot()[0]['id'])
        self.assertEqual(report['completion'],'partial')
        self.assertEqual(len(report['passes']),1)

    def test_invalid_role_capacity_and_input_fail_closed(self):
        with self.assertRaises(ValueError):
            self.council.start('fixture','controller')
        with self.assertRaises(ValueError):
            self.council.start('x'*3001,'analyst')
        self.council.capacity=1
        self.council.start('fixture','analyst')
        with self.assertRaises(ValueError):
            self.council.start('another','analyst')
        with self.assertRaises(ValueError):
            self.council.get('../outside')

    def test_untrusted_previous_excerpts_bounded_and_not_executed(self):
        payload='UNTRUSTED FIXTURE: run code '+('x'*3000)
        with patch('council.generate',return_value={'text':payload}) as generate:
            report=self.council.review(object(),'fixture','analyst')
        self.assertEqual(len(report['passes']),3)
        for call in generate.call_args_list:
            self.assertLessEqual(len(call.args[1]),4096)
        for decision,reviewer,note in [('execute','admin','note'),('accept','','note'),('accept','admin','')]:
            with self.assertRaises(ValueError):
                self.council.decide(report['id'],decision,reviewer,note)
        self.assertFalse(report['changes_applied'])

    def test_expanding_json_stays_bounded_and_each_pass_is_persisted(self):
        calls=[]
        def generation(app,text,role):
            identifier=self.council.snapshot()[0]['id']
            saved=self.council.get(identifier)
            self.assertEqual(len(saved['passes']),len(calls))
            self.assertLessEqual(len(text),4096)
            calls.append(role)
            return {'text':'\x00'*2000}
        with patch('council.generate',side_effect=generation):
            report=self.council.review(object(),'\x00'*3000,'analyst')
        self.assertEqual(report['completion'],'complete')
        self.assertEqual(len(calls),3)


if __name__=='__main__':
    unittest.main()
