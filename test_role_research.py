"""Source-routing fixtures, never public findings or qualified training data."""
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch
from evidence_store import EvidenceStore
from role_research import RoleResearch,profiles,DORK_ROLES
import source_transport


class RoleResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.workspace=RoleResearch(EvidenceStore(root/'evidence'),root/'role-research')

    def response(self,url,bound):
        if 'github.com' in url:
            item={'full_name':'fixture/tool','html_url':'https://github.com/fixture/tool','description':'security fixture','license':{'spdx_id':'MIT'},'created_at':'2025-01-01T00:00:00Z','owner':{'email':'excluded@example.invalid'}}
        else:
            host='security.stackexchange.com' if 'site=security' in url else 'stackoverflow.com'
            item={'question_id':123,'link':f'https://{host}/questions/123/fixture','title':'Fixture discussion','body':'<p>Fixture only</p>','creation_date':1700000000,'content_license':'CC BY-SA 4.0','owner':{'display_name':'Fixture author','link':f'https://{host}/users/123/fixture','email':'excluded@example.invalid'},'tags':['fixture']}
        return json.dumps({'items':[item],'quota_remaining':100}).encode()

    def test_every_role_has_bounded_exact_provider_queries(self):
        selected=profiles();self.assertEqual(len(selected),66)
        for value in selected.values():
            self.assertIn(len(value['providers']),(0,3))
            if not value['providers']:self.assertFalse(value['collection_enabled'])
            for provider in value['providers']:
                source_transport.validate(provider['url'])
                with self.assertRaises(ValueError):source_transport.validate(provider['url']+'&page=999')
        with self.assertRaises(ValueError):source_transport.validate('https://api.github.com/search/repositories?q=arbitrary')

    def test_collection_quarantines_attribution_and_metadata_without_email(self):
        report=self.workspace.collect('web_red',self.response)
        self.assertEqual(len(report['items']),3)
        self.assertTrue(all(row['status']=='retrieved' for row in report['requests']))
        self.assertFalse(report['training_occurred'])
        records=self.workspace.store.list_records()
        self.assertTrue(all(row['status']=='quarantine' for row in records))
        self.assertNotIn('excluded@example.invalid',json.dumps(records))
        self.assertTrue(any(row['normalized'].get('attribution',{}).get('name')=='Fixture author' for row in records))
        self.assertTrue(any(row['normalized'].get('kind')=='tool_proposal' for row in records))

    def test_backoff_applies_across_stackexchange_sites(self):
        calls=[]
        def fetch(url,bound):
            calls.append(url);value=json.loads(self.response(url,bound))
            if 'stackexchange' in url:value['backoff']=120
            return json.dumps(value).encode()
        result=self.workspace.collect('web_red',fetch)
        self.assertEqual(len(calls),2)
        self.assertEqual(result['requests'][1]['status'],'backoff')

    def test_dork_access_is_role_and_scope_bound(self):
        self.assertNotIn('satellite_red',DORK_ROLES)
        with self.assertRaises(ValueError):self.workspace.dorks('web_red')
        request={'role':'web_red','enabled':True,'scope_type':'domain','scope':'example.invalid','confirmed':True}
        self.workspace.dork_access(request)
        result=self.workspace.dorks('web_red')
        self.assertEqual(len(result['templates']),3)
        self.assertTrue(all('site:example.invalid' in item['query'] for item in result['templates']))
        for change in ({'role':'satellite_red'},{'scope':'example.invalid OR unowned.invalid'},{'scope':'https://example.invalid'},{'confirmed':False}):
            with self.assertRaises(ValueError):self.workspace.dork_access(dict(request,**change))
        with self.assertRaises(ValueError):self.workspace.dorks('web_blue')
        self.workspace.dork_access(dict(request,enabled=False))
        with self.assertRaises(ValueError):self.workspace.dorks('web_red')

    def test_export_creates_red_and_blue_source_corpora_and_checks_hash(self):
        row={'name':'fixture reference','url':'https://example.invalid/reference','sha256':'a'*64,'snapshot_at':'2026-10-20T00:00:00Z','excerpt':'Explicit unit-test reference fixture','score':.5}
        with patch('knowledge.lookup',return_value={'results':[row]}):result=self.workspace.build_datasets()
        self.assertEqual(len(result['roles']),66)
        self.assertEqual({value['lane'] for value in result['roles'].values()},{'red','blue'})
        self.assertFalse(result['training_eligible'])
        exported=json.loads(self.workspace.dataset('web_red').splitlines()[0])
        self.assertEqual(exported['admission'],'quarantine')
        path=self.workspace.root/result['roles']['web_red']['file'];path.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):self.workspace.dataset('web_red')

    def test_gzip_api_decoding_has_decompressed_bound(self):
        url=profiles()['web_red']['providers'][0]['url']
        for raw,bound,valid in [(b'{"items":[]}',1024,True),(b'x'*2000,256,False)]:
            opener=MagicMock();response=opener.open.return_value.__enter__.return_value
            response.headers={'Content-Encoding':'gzip'};response.read.return_value=gzip.compress(raw)
            with patch('source_transport.build_opener',return_value=opener):
                if valid:self.assertEqual(source_transport.direct_fetch(url,bound),raw)
                else:
                    with self.assertRaisesRegex(ValueError,'Decompressed'):source_transport.direct_fetch(url,bound)


if __name__=='__main__':unittest.main()
