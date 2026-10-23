"""Explicit fixtures exercise admission/training contracts, not model capability."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from evidence_store import EvidenceStore, packed
from poc_training import PocTraining, FEATURES, TASK, SCHEMA, feature_vector


class PocTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.store=EvidenceStore(root/'evidence')
        self.trainer=PocTraining(self.store,root/'candidates')

    def datasets(self):
        manifests={};self.members={}
        checks={key:True for key in ('provenance_valid','license_permits_use','privacy_reviewed','real_data_reviewed','labels_valid','dataset_eligible','schema_valid','features_complete')}
        for split,start in [('train',1),('validation',5),('test',9)]:
            members=[]
            for index in range(start,start+4):
                # Unique configuration vectors and unique source markers are test
                # fixtures. The declared provenance below is fixture input only.
                features={key:((index*(k+1))%17)/17 for k,key in enumerate(FEATURES)}
                value={'fixture_identity':f'observation-{index}',
                       'poc_features':features,'poc_labels':{'reproduced':index%2,'mitigation_verified':(index+1)%2}}
                record={'source_url':f'https://example.invalid/lab-fixture/{index}',
                    'retrieved_at':'2026-10-20T00:00:00Z','normalized':value,
                    'content_sha256':hashlib.sha256(packed(value).encode()).hexdigest(),
                    'license':{'status':'verified','evidence_url':'https://example.invalid/test-license'},
                    'synthetic_status':'authorized_observation','label_origin':'instrument_measurement',
                    'training_task':TASK,'extraction_schema':SCHEMA,'method':'explicit unit-test fixture'}
                member=self.store.ingest(record)
                self.store.review(member['record_id'],member['version_id'],'accept_training','fixture reviewer','fixture admission only',checks)
                members.append(member)
            self.members[split]=members
            frozen=self.store.freeze_dataset('fixture-'+split,'training' if split=='train' else 'evaluation',members,'fixture reviewer')
            manifests[split]=frozen['manifest_id']
        return manifests

    def test_real_candidate_roundtrip_and_revocation(self):
        selection=self.datasets()
        report=self.trainer.train({'datasets':selection,'confirmed':True})
        self.assertEqual(set(report['models']),{'poc_red','poc_blue'})
        self.assertTrue(report['training_occurred']);self.assertFalse(report['promoted'])
        self.assertEqual(self.trainer.status()['status'],'candidate')
        predicted=self.trainer.predict({key:.5 for key in FEATURES})
        self.assertEqual(predicted['execution'],'none')
        self.assertTrue(all(0<=row['estimated_probability']<=1 for row in predicted['predictions'].values()))
        member=self.members['test'][0]
        self.store.review(member['record_id'],member['version_id'],'quarantine','fixture reviewer','fixture revocation',{})
        self.assertEqual(self.trainer.status()['status'],'invalidated')
        with self.assertRaises(ValueError):self.trainer.predict({key:.5 for key in FEATURES})

    def test_confirmation_missing_or_invalid_data_creates_no_weights(self):
        for value in ({},{'datasets':{},'confirmed':False},{'datasets':{},'confirmed':True}):
            with self.assertRaises(ValueError):self.trainer.train(value)
        self.assertFalse(list(self.trainer.root.rglob('*.pt')))
        self.assertEqual(self.trainer.status()['status'],'awaiting_admitted_data')

    def test_manifest_and_validation_test_overlap_rejected(self):
        selection=self.datasets()
        bad=dict(selection,validation=selection['test'])
        with self.assertRaisesRegex(ValueError,'distinct'):self.trainer.train({'datasets':bad,'confirmed':True})
        overlap=self.store.freeze_dataset('fixture overlapping evaluation','evaluation',self.members['validation'],'fixture reviewer')
        bad=dict(selection,test=overlap['manifest_id'])
        with self.assertRaisesRegex(ValueError,'crosses split'):self.trainer.train({'datasets':bad,'confirmed':True})
        self.assertFalse(list(self.trainer.root.rglob('*.pt')))

    def test_features_and_checkpoint_integrity(self):
        for value in ({},{key:True for key in FEATURES},{key:float('nan') for key in FEATURES}):
            with self.assertRaises(ValueError):feature_vector(value)
        report=self.trainer.train({'datasets':self.datasets(),'confirmed':True})
        path=self.trainer.root/report['run_id']/'poc_red.pt'
        path.write_bytes(b'fixture corruption')
        self.assertEqual(self.trainer.status()['status'],'invalidated')
        with self.assertRaises(ValueError):self.trainer.predict({key:0 for key in FEATURES})


if __name__=='__main__':unittest.main()
