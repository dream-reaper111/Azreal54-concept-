"""Caller-supplied CSV data must not inherit an unverified upstream identity."""
import csv
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import model


class TrainingProvenanceTests(unittest.TestCase):
    def test_local_csv_does_not_claim_official_or_measured_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'files_exploits.csv'
            with path.open('w',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=['description','type'])
                writer.writeheader()
                writer.writerow({'description':'Explicit synthetic fixture','type':'fixture'})
            tasks,provenance=model.training_rows(SimpleNamespace(csv=str(path),synthetic_count=1,custom=[]))
            self.assertEqual(tasks['exploit'],[('Explicit synthetic fixture','fixture')])
            self.assertEqual(provenance['exploit_source'],'operator_supplied_local_csv')
            self.assertEqual(provenance['exploit_source_verification'],'not_independently_verified')
            self.assertEqual(provenance['exploit_synthetic_status'],'unknown')
            self.assertEqual(len(provenance['exploit_csv_sha256']),64)
