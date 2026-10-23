"""Explicit fixtures test collection contracts; fixtures are not operational evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import hak5_catalog
from evidence_store import EvidenceStore
from source_transport import validate


def fixture(name='example'):
    return {'name': name, 'full_name': 'hak5/'+name, 'html_url': 'https://github.com/hak5/'+name, 'owner': {'login':'hak5', 'email':'omit@example.test'}, 'description':'wireless reference fixture', 'fork':False, 'archived':False, 'default_branch':'main', 'created_at':'2020-01-01T00:00:00Z', 'updated_at':'2020-01-02T00:00:00Z', 'pushed_at':'2020-01-02T00:00:00Z', 'contributors':[{'email':'omit@example.test'}], 'license':{'spdx_id':'MIT'}}


class Hak5Tests(unittest.TestCase):
    def test_quarantine_privacy_routing_and_search(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            fetch=Mock(return_value=json.dumps([fixture()]).encode())
            report=hak5_catalog.refresh(root/'evidence',fetch)
            self.assertEqual((report['items'],report['accepted'],report['quarantined']), (1,0,1))
            self.assertFalse(report['training_occurred'])
            fetch.assert_called_once_with(hak5_catalog.URL.format(1),1_000_000)
            rows=EvidenceStore(root/'evidence').list_records()
            self.assertEqual(rows[0]['metadata']['task_routes'],[])
            self.assertEqual(rows[0]['metadata']['license']['status'],'unknown')
            self.assertIsNone(rows[0]['metadata']['publication_at'])
            self.assertEqual(rows[0]['normalized']['created_at'],'2020-01-01T00:00:00Z')
            snapshot=(root/report['source_snapshot']).read_text()
            self.assertNotIn('omit@example.test',snapshot)
            self.assertNotIn('contributors',json.loads(snapshot)['repositories'][0])
            result=hak5_catalog.search('wireless',root)
            self.assertEqual(result[0]['retrieval_kind'],'stored_snapshot')
            self.assertEqual(result[0]['url'],'https://github.com/hak5/example')
            self.assertEqual(result[0]['evidence_status'],'quarantine')

    def test_identity_validation(self):
        for key,value in [('owner',{'login':'other'}),('full_name','other/example'),('html_url','https://example.com/')]:
            item=fixture();item[key]=value
            with self.assertRaises(ValueError):hak5_catalog.sanitize(item)

    def test_bounded_pagination(self):
        with tempfile.TemporaryDirectory() as directory:
            def fetch(url,bound):
                page=int(url.rsplit('=',1)[1])
                return json.dumps([fixture(f'item-{page}-{n}') for n in range(100)]).encode()
            report=hak5_catalog.refresh(Path(directory)/'evidence',fetch)
            self.assertEqual(report['items'],300)
            self.assertEqual(len(report['pages']),3)
            self.assertTrue(report['truncated'])

    def test_no_automatic_fetch_and_exact_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(hak5_catalog.search('anything',Path(directory)),[])
        for page in range(1,4):validate(hak5_catalog.URL.format(page))
        with self.assertRaises(ValueError):validate(hak5_catalog.URL.format(4))


if __name__=='__main__':unittest.main()
