"""Real subprocess supervision and public evidence boundary checks."""
import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json
import shutil
import tool_broker
import live_data
from source_transport import validate
from import_broker import allowed
from public_sources import SOURCES
from lab import Bus

class Runtime(unittest.TestCase):
    def test_real_curl_process(self):
        if not shutil.which('curl',path='/usr/bin:/bin'):self.skipTest('curl not installed on test host')
        spec={'tool':'curl','argv':['curl','--version'],'target':'local://tool-version','timeout':3}
        with patch.dict(tool_broker.RECIPES,{'test_version':spec}):result=tool_broker.run_recipe('test_version')
        self.assertEqual(result['exit_code'],0)
        self.assertTrue(base64.b64decode(result['output_b64']).startswith(b'curl '))
        self.assertFalse(tool_broker.PENDING)

    def test_real_output_retention_and_scope_validation(self):
        import runtime_tools
        if not shutil.which('curl',path='/usr/bin:/bin'):self.skipTest('curl not installed')
        spec={'tool':'curl','argv':['curl','--version'],'target':'local://tool-version','timeout':3}
        approval={'operation':'recipe_test_version','target':spec['target'],'request_id':'test-owned-evidence','model':'obsidian'}
        with patch.dict(tool_broker.RECIPES,{'test_version':spec}):
            observed=tool_broker.run_recipe('test_version')
            with tempfile.TemporaryDirectory() as folder:
                with patch.object(runtime_tools,'ROOT',Path(folder)),patch.object(runtime_tools,'broker',return_value=dict(observed)):
                    retained=runtime_tools.execute(approval)
                self.assertTrue(Path(retained['evidence_path']).read_bytes().startswith(b'curl '))
                self.assertTrue((Path(retained['evidence_path']).parent/'manifest.json').is_file())
                invalid=dict(observed,target='outside-scope')
                with patch.object(runtime_tools,'ROOT',Path(folder)),patch.object(runtime_tools,'broker',return_value=invalid):
                    with self.assertRaisesRegex(ValueError,'scope mismatch'):runtime_tools.execute(approval)

    def test_timeout_cleanup_and_capacity(self):
        if not Path('/usr/bin/python3').exists():self.skipTest('System Python missing')
        cases=[('import time; print("started",flush=True); time.sleep(10)',.1,True,False),
               ('import os; os.write(1,b"x"*300000)',3,False,True)]
        for code,timeout,timed_out,truncated in cases:
            spec={'tool':'python3','argv':['python3','-c',code],'target':'local://supervision-fixture','timeout':timeout}
            with patch.dict(tool_broker.RECIPES,{'test_process':spec}):result=tool_broker.run_recipe('test_process')
            self.assertEqual(result['timed_out'],timed_out)
            self.assertEqual(result['output_truncated'],truncated)
            self.assertLessEqual(len(base64.b64decode(result['output_b64'])),tool_broker.LIMIT)
            self.assertFalse(tool_broker.PENDING)

    def test_model_plan_format_and_authority(self):
        from tool_plans import parse
        plan={'steps':[{'recipe':'http_headers','reason':'Inspect owned lab response headers.'}]}
        for text in (json.dumps(plan),'```json\n'+json.dumps(plan)+'\n```'):
            self.assertEqual(parse(text),plan)
        for text in ('Here is a plan: '+json.dumps(plan),
                     '{"steps":[],"steps":[]}',
                     '{"steps":[{"recipe":"shell","reason":"bad"}]}',
                     '{"steps":[{"recipe":"http_headers","reason":"x","target":"outside"}]}'):
            with self.assertRaises(ValueError):parse(text)

    def test_source_allowlist(self):
        for url in SOURCES.values():
            validate(url)
            self.assertTrue(allowed(url))
        for url in ('http://www.cisa.gov/private','https://www.cisa.gov/other','https://raw.githubusercontent.com/other/repo/main/a','https://evil.invalid/a'):
            with self.assertRaises(ValueError):validate(url)
            self.assertFalse(allowed(url))

    def test_observed_feed_provenance(self):
        record={'cveID':'CVE-2025-12345','vendorProject':'fixture vendor','dateAdded':'2025-01-01'}
        raw=json.dumps({'count':1,'catalogVersion':'test-fixture','vulnerabilities':[record]}).encode()
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(live_data,'ROOT',Path(temp)),patch.object(live_data,'fetch',return_value=raw):
                result=live_data.collect('vendor','obsidian',Bus())
            self.assertEqual(Path(result['raw_evidence_path']).read_bytes(),raw)
            self.assertEqual(result['matched_records'],1)
            self.assertFalse(result['training_performed'])
        with patch.object(live_data,'fetch',side_effect=OSError('offline')):
            with self.assertRaisesRegex(ValueError,'no cached snapshot'):live_data.collect('*','obsidian',Bus())

    def test_invalid_catalog_not_silently_accepted(self):
        for value in ({'count':2,'vulnerabilities':[]},{'count':1,'vulnerabilities':[{'cveID':'bad'}]}):
            with self.assertRaises(ValueError):live_data.parse(json.dumps(value).encode())

if __name__=='__main__':unittest.main()
