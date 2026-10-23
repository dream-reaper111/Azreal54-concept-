"""Collection-boundary fixtures; these tests establish no remote-source behavior."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import collection


class CollectionTests(unittest.TestCase):
    def test_fixed_sources_bounded_concurrency_and_no_raw_retention(self):
        state = {'active': 0, 'peak': 0}
        lock = threading.Lock()
        records = []

        class Store:
            def __init__(self, root):
                pass

            def ingest(self, record, raw=None):
                self_test.assertIsNone(raw)
                records.append(record)
                return {'record_id': str(len(records)), 'version_id': '1', 'status': 'quarantined'}

        def fetch(url, bound):
            with lock:
                state['active'] += 1
                state['peak'] = max(state['peak'], state['active'])
            try:
                if 'uci.edu' in url:
                    return json.dumps({'data': {'uci_id': int(url.split('=')[-1]), 'abstract': 'fixture', 'num_features': 0}}).encode()
                if 'cisa.gov' in url:
                    return json.dumps({'vulnerabilities': [{'cveID': 'CVE-fixture', 'secret': 'excluded'}]}).encode()
                return json.dumps({'tag_name': 'fixture', 'author': {'login': 'excluded'}}).encode()
            finally:
                with lock:
                    state['active'] -= 1

        self_test = self
        with tempfile.TemporaryDirectory() as temporary, patch('evidence_store.EvidenceStore', Store):
            result = collection.run(Path(temporary), fetch)
        self.assertEqual(result['retrieved'], 5)
        self.assertEqual(result['quarantined'], 5)
        self.assertFalse(result['training_occurred'])
        self.assertLessEqual(state['peak'], 2)
        self.assertEqual(sum(s[2] for s in collection.SOURCES), 5_000_000)
        self.assertNotIn('excluded', json.dumps(records))
        self.assertTrue(all(r['privacy_review'] == 'pending' for r in records))
        self.assertTrue(all(r['provenance']['intended_use'] == 'reference_only' for r in records))
        self.assertEqual(next(r for r in records if r['source_url'].endswith('=422'))['task_routes'], ['rf_red', 'rf_blue'])
        self.assertEqual(result['authorized_operational']['status'], 'awaiting_authorized_input')

    def test_invalid_or_oversize_responses_not_ingested(self):
        class Store:
            def __init__(self, root):
                pass

            def ingest(self, *args, **kwargs):
                raise AssertionError('invalid content must not be ingested')

        def fetch(url, bound):
            return b'x' * (bound + 1) if 'uci.edu' in url else b'invalid-json'

        with patch('evidence_store.EvidenceStore', Store):
            result = collection.run(Path('/unused-test-root'), fetch)
        self.assertEqual(result['rejected'], 5)
        self.assertEqual(result['retrieved'], 0)
        self.assertEqual(result['accepted'], 0)

    def test_policy_binds_all_roles_and_prohibits_training_on_collection(self):
        value = collection.policy()
        self.assertEqual(value['role_count'], 66)
        self.assertIn(f"all {value['role_count']} roles", value['applies_to'])
        self.assertIn('never automatic production training', ' '.join(value['training']))


if __name__ == '__main__':
    unittest.main()
