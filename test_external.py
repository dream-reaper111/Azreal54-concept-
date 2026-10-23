"""External authorization contracts; no third-party requests are made by these tests."""
import base64
from datetime import datetime,timezone,timedelta
import json
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import external_targets as targets
import external_broker
import permissions
from admin import ROLES
from directives import Directives

class External(unittest.TestCase):
    def setUp(self):external_broker.USED.clear()
    def approval(self):return {'request_id':'a'*24,'model':'obsidian','operation':'external_http_headers','target':'https://example.com/','expires_at':(datetime.now(timezone.utc)+timedelta(minutes=4)).isoformat()}
    def test_every_role_can_request_but_cannot_bypass_approval(self):
        for role,_,_,_ in ROLES:
            result=permissions.proposal({'model':role,'operation':'external_http_headers','section':'external','target':'https://example.com/'},allow_runtime=True)
            self.assertEqual(result['status'],'pending')
            self.assertEqual(result['uses_left'],1)
        with self.assertRaises(ValueError):permissions.proposal({'model':'obsidian','operation':'external_http_headers','target':'https://example.com/'})
    def test_public_target_contract(self):
        for url in ('https://example.com/path','http://1.1.1.1/'):
            self.assertEqual(targets.parse_target(url)['url'],url)
        for url in ('file:///etc/passwd','http://127.0.0.1/','http://169.254.169.254/','http://10.0.0.1/','https://user:pass@example.com/','https://example.com/?token=x','https://example.com:8443/','https://example.com/#fragment','https://example.com/\n'):
            with self.assertRaises(ValueError,msg=url):targets.parse_target(url)
    def test_dns_pin_and_rebinding_rejection(self):
        with patch.object(targets.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stdout=b'["1.1.1.1","127.0.0.1"]')):
            with self.assertRaises(ValueError):targets.resolve_public('https://example.com/')
        recipe=targets.contract('https://example.com/path','1.1.1.1')
        self.assertIn('example.com:443:1.1.1.1',recipe['argv'])
        self.assertEqual(recipe['argv'][-2:],['--','https://example.com/path'])
        self.assertNotIn('--location',recipe['argv'])
    def test_expiry_unknown_methods_and_replay(self):
        approval=self.approval()
        for changed in (dict(approval,operation='shell'),dict(approval,expires_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())):
            with self.assertRaises(ValueError):targets.validate_approval(changed)
        with patch.object(external_broker,'resolve_public',side_effect=ValueError('not public')):
            with self.assertRaises(ValueError):external_broker.execute(approval)
        with self.assertRaisesRegex(ValueError,'consumed'):external_broker.execute(approval)
    def test_cookie_credentials_redacted_without_claiming_execution(self):
        raw=b'HTTP/1.1 200 OK\r\nSet-Cookie: session=FIXTURE\r\n continuation\r\nServer: fixture\r\n\r\n'
        fixture={'output_b64':base64.b64encode(raw).decode()}
        with patch.object(external_broker,'resolve_public',return_value='1.1.1.1'),patch.object(external_broker,'run_contract',return_value=fixture):
            result=external_broker.execute(self.approval())
        retained=base64.b64decode(result['output_b64'])
        self.assertNotIn(b'session=FIXTURE',retained)
        self.assertNotIn(b'continuation',retained)
        self.assertIn(b'Server: fixture',retained)
        self.assertEqual(result['redacted_cookie_lines'],2)
    def test_published_lookup_is_a_snapshot_and_validation_stays_a_plan(self):
        import exploit_references
        result=exploit_references.search('OpenSSH')
        self.assertEqual(result['collection_kind'],'stored_snapshot')
        self.assertIsNone(result['collection_time'])
        self.assertGreater(result['examined_records'],0)
        self.assertFalse(result['execution_performed'])
        self.assertFalse(result['training_occurred'])
        plan=permissions.proposal({'model':'scada_red','operation':'published_exploit_validation','section':'external','target':'user-designated-system'})
        self.assertFalse(plan['executable'])
        self.assertEqual(plan['status'],'pending')

    def test_admin_directives_persist_without_execution_grants(self):
        with tempfile.TemporaryDirectory() as folder:
            roles={r[0] for r in ROLES};engine=Directives(Path(folder),roles)
            result=engine.assign('all','black_hat','Review published weaknesses; request exact test approval.')
            self.assertEqual(result['updated_roles'],66)
            self.assertFalse(result['execution_authority_changed'])
            engine.assign('obsidian','white_hat','Review privacy exposure.')
            self.assertTrue(list(Path(folder).glob('directives-backup-*.json')))
            loaded=Directives(Path(folder),roles)
            self.assertEqual(loaded.snapshot()['assignments']['obsidian']['profile'],'white_hat')
            self.assertIn('unauthorized',loaded.snapshot()['definitions']['black_hat']['definition'])
            style=loaded.snapshot()['problem_solving_directive'].lower()
            self.assertIn('think outside the box',style)
            self.assertIn('loophole-finding is welcome',style)
            self.assertIn('authorized azrael range',style)
            self.assertIn('target allowlists',style)
            self.assertIn('without pursuing them',style)
            with self.assertRaises(ValueError):engine.assign('unknown','black_hat','x')

if __name__=='__main__':unittest.main()
