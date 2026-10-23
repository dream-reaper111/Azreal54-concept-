"""Synthetic fixtures exercise storage rules only; they are not operational evidence."""
import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from evidence_store import EvidenceStore


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=EvidenceStore(Path(self.tmp.name))
        self.raw=b'fixture original source bytes'
        self.record={'source_url':'https://example.invalid/fixture','retrieved_at':'2026-10-20T00:00:00Z',
          'content_sha256':hashlib.sha256(self.raw).hexdigest(),
          'normalized':{'text':'explicit storage test fixture'},'license':{'status':'unknown'},
          'method':'unit test fixture','worker':'test','synthetic_status':'declared_synthetic'}

    def admit(self, record=None):
        r=copy.deepcopy(record or self.record)
        # These declarations are test fixture inputs, not evidence about real activity.
        r.update(license={'status':'verified','evidence_url':'https://example.invalid/license'},
          synthetic_status='documented_measurement',label_origin='instrument_measurement',training_task='fixture',extraction_schema='fixture-v1')
        result=self.store.ingest(r)
        checks={k:True for k in ('provenance_valid','license_permits_use','privacy_reviewed',
          'real_data_reviewed','labels_valid','dataset_eligible','schema_valid','features_complete')}
        self.store.review(result['record_id'],result['version_id'],'accept_training','fixture reviewer','fixture admission',checks)
        return result

    def test_hash_and_default_quarantine(self):
        with self.assertRaises(ValueError):
            self.store.ingest(self.record,b'different')
        got=self.store.ingest(self.record,self.raw)
        self.assertEqual(got['status'],'quarantine')
        self.assertFalse(got['training_occurred'])
        path=next((Path(self.tmp.name)/'raw').iterdir())
        self.assertEqual(path.stat().st_mode & 0o777,0o600)
        self.assertEqual(path.read_bytes(),self.raw)
        with self.assertRaises(ValueError):
            self.store.review(got['record_id'],got['version_id'],'accept_reference','a','b',{})

    def test_retrievals_and_corrections_immutable(self):
        first=self.store.ingest(self.record)
        r=copy.deepcopy(self.record);r['retrieved_at']='2026-10-21T00:00:00Z'
        second=self.store.ingest(r)
        self.assertEqual(first['version_id'],second['version_id'])
        self.assertTrue(second['is_duplicate'])
        r['normalized']['text']='corrected fixture';r['corrections']={'source_says':'corrected'}
        third=self.store.ingest(r)
        trace=self.store.trace(first['record_id'])
        self.assertEqual(len(trace['versions']),2)
        self.assertEqual(len(trace['retrievals']),3)
        self.assertNotEqual(first['version_id'],third['version_id'])
        self.assertEqual(trace['versions'][0]['normalized']['text'],'explicit storage test fixture')

    def test_training_gates(self):
        r=copy.deepcopy(self.record);r['license']={'status':'verified'}
        got=self.store.ingest(r)
        checks={k:True for k in ('provenance_valid','license_permits_use','privacy_reviewed','real_data_reviewed','labels_valid','dataset_eligible','schema_valid','features_complete')}
        with self.assertRaises(ValueError):
            self.store.review(got['record_id'],got['version_id'],'accept_training','a','b',checks)
        self.store.review(got['record_id'],got['version_id'],'accept_reference','a','b',checks)
        with self.assertRaises(ValueError):
            self.store.freeze_dataset('fixture','training',[got],'a')

    def test_frozen_split_guards_exact_duplicate_and_identity(self):
        first=self.admit()
        frozen=self.store.freeze_dataset('fixture-eval','evaluation',[first],'fixture reviewer')
        self.assertTrue(frozen['valid'])
        r=copy.deepcopy(self.record);r['source_url']='https://example.invalid/mirror'
        mirror=self.admit(r)
        self.assertTrue(mirror['is_duplicate'])
        with self.assertRaises(ValueError):
            self.store.freeze_dataset('fixture-training','training',[mirror],'fixture reviewer')
        r['source_url']=self.record['source_url'];r['content_sha256']='b'*64;r['normalized']={'text':'different content'}
        corrected=self.admit(r)
        with self.assertRaises(ValueError):
            self.store.freeze_dataset('fixture-training','training',[corrected],'fixture reviewer')

    def test_near_duplicates_retain_sources(self):
        r=copy.deepcopy(self.record)
        r['normalized']={'text':' '.join('word'+str(i) for i in range(30))}
        first=self.store.ingest(r)
        r['source_url']='https://example.invalid/mirror';r['content_sha256']='c'*64
        r['normalized']['text']+=' extra'
        second=self.store.ingest(r)
        self.assertEqual(first['duplicate_cluster_id'],second['duplicate_cluster_id'])
        self.assertEqual(self.store.summary()['records'],2)

    def test_late_duplicate_bridge_invalidates_frozen_splits(self):
        r=copy.deepcopy(self.record)
        r['normalized']={'text':' '.join('token'+str(i) for i in range(90))}
        r['content_sha256']='a'*64
        a=self.admit(r)
        r['source_url']='https://example.invalid/second'
        r['normalized']={'text':' '.join('token'+str(i) for i in range(10,100))}
        r['content_sha256']='b'*64
        b=self.admit(r)
        self.assertNotEqual(a['duplicate_cluster_id'],b['duplicate_cluster_id'])
        self.store.freeze_dataset('fixture-eval','evaluation',[a],'fixture reviewer')
        self.store.freeze_dataset('fixture-training','training',[b],'fixture reviewer')
        r['source_url']='https://example.invalid/bridge'
        r['normalized']={'text':' '.join('token'+str(i) for i in range(100))}
        r['content_sha256']='c'*64
        self.admit(r)
        self.assertEqual(self.store.summary()['invalidated_datasets'],2)
        with self.assertRaises(ValueError):
            self.store.freeze_dataset('fixture-new','training',[b],'fixture reviewer')

    def test_delete_tombstone_invalidates_and_purges(self):
        first=self.admit()
        # Explicit raw retention remains independent of normalized admission.
        r=copy.deepcopy(self.record)
        r.update(license={'status':'verified','evidence_url':'https://example.invalid/license'},
          synthetic_status='documented_measurement',label_origin='instrument_measurement',training_task='fixture',extraction_schema='fixture-v1')
        self.store.ingest(r,self.raw)
        self.store.freeze_dataset('fixture-eval','evaluation',[first],'fixture reviewer')
        self.store.delete_record(first['record_id'],'fixture deletion')
        trace=self.store.trace(first['record_id'])
        self.assertIn('tombstone',trace)
        self.assertNotIn('versions',trace)
        self.assertFalse(trace['datasets'][0]['valid'])
        self.assertFalse(list((Path(self.tmp.name)/'raw').iterdir()))
        with self.assertRaises(ValueError):
            self.store.ingest(r)

    def test_retention_and_capacity(self):
        store=EvidenceStore(Path(self.tmp.name)/'bounded',max_records=1)
        store.ingest(self.record)
        r=copy.deepcopy(self.record);r['source_url']='https://example.invalid/second'
        with self.assertRaises(ValueError):
            store.ingest(r)
        self.assertEqual(store.expire_retention('2100-01-01T00:00:00Z')['expired_records'],1)

    def test_public_records_and_observations_admitted_with_explicit_schema(self):
        for status in ('documented_public_record','authorized_observation'):
            r=copy.deepcopy(self.record)
            r.update(source_url='https://example.invalid/'+status,license={'status':'verified'},
              synthetic_status=status,label_origin='official_record',training_task='severity',extraction_schema='cvss-v3')
            got=self.store.ingest(r)
            checks={k:True for k in ('provenance_valid','license_permits_use','privacy_reviewed',
              'real_data_reviewed','labels_valid','dataset_eligible','schema_valid','features_complete')}
            self.store.review(got['record_id'],got['version_id'],'accept_training','fixture','fixture',checks)
            frozen=self.store.freeze_dataset('fixture','training',[got],'fixture')
            self.assertFalse(frozen['training_ready'])

    def test_raw_deletion_rejects_corrupted_path_and_symlink_directory(self):
        got=self.store.ingest(self.record,self.raw)
        unrelated=Path(self.tmp.name)/'unrelated';unrelated.write_bytes(b'keep')
        original=str(self.store.raw/(got['version_id']+'.bin'))
        with self.store.connect() as con:
            con.execute('UPDATE versions SET raw_path=? WHERE id=?',(str(unrelated),got['version_id']))
        with self.assertRaises(ValueError):
            self.store.delete_record(got['record_id'],'fixture')
        self.assertEqual(unrelated.read_bytes(),b'keep')
        self.assertEqual(len(self.store.trace(got['record_id'])['versions']),1)
        with self.store.connect() as con:
            con.execute('UPDATE versions SET raw_path=? WHERE id=?',(original,got['version_id']))
        moved=Path(self.tmp.name)/'original-raw'
        self.store.raw.rename(moved)
        self.store.raw.symlink_to(moved,target_is_directory=True)
        with self.assertRaises(OSError):
            self.store.delete_record(got['record_id'],'fixture')
        self.assertTrue((moved/(got['version_id']+'.bin')).exists())
        self.store.raw.unlink();moved.rename(self.store.raw)
        self.assertTrue(self.store.delete_record(got['record_id'],'fixture')['deleted'])

    def test_trace_paging_reports_complete_coverage(self):
        got=self.store.ingest(self.record)
        self.store.ingest(self.record)
        first=self.store.trace(got['record_id'],limit=1)
        self.assertEqual(first['coverage']['retrievals']['total'],2)
        self.assertTrue(first['coverage']['retrievals']['has_more'])
        second=self.store.trace(got['record_id'],limit=1,offset=1)
        self.assertNotEqual(first['retrievals'][0]['id'],second['retrievals'][0]['id'])
        with self.assertRaises(ValueError):
            self.store.trace(got['record_id'],limit=101)

    def test_compact_listing_omits_normalized_and_reports_latest_retrieval(self):
        self.store.ingest(self.record)
        r=copy.deepcopy(self.record);r['retrieved_at']='2026-10-21T00:00:00Z'
        self.store.ingest(r)
        compact=self.store.list_records(include_normalized=False)
        self.assertNotIn('normalized',compact[0])
        self.assertEqual(compact[0]['content_sha256'],self.record['content_sha256'])
        self.assertEqual(self.store.list_records()[0]['content_sha256'],self.record['content_sha256'])
        self.assertEqual(compact[0]['retrieved_at'],'2026-10-21T00:00:00+00:00')
        self.assertEqual(self.store.list_records()[0]['normalized'],self.record['normalized'])

    def test_source_date_precision_and_timestamp_boundaries(self):
        r=copy.deepcopy(self.record)
        r.update(publication_at='2026-10-01',event_at='2026-09-30')
        got=self.store.ingest(r)
        metadata=self.store.trace(got['record_id'])['versions'][0]['metadata']
        self.assertEqual(metadata['publication_at'],'2026-10-01')
        self.assertEqual(metadata['event_at'],'2026-09-30')
        for field,value in [('retrieved_at',None),('retrieved_at','2026-10-01'),
                            ('publication_at',17),('event_at','2026-02-30')]:
            invalid=copy.deepcopy(r);invalid[field]=value
            with self.assertRaises(ValueError):
                self.store.ingest(invalid)

    def test_nonfinite_values_rejected_in_normalized_or_metadata(self):
        for value in (float('nan'),float('inf'),float('-inf')):
            r=copy.deepcopy(self.record);r['normalized']['number']=value
            with self.assertRaises(ValueError):
                self.store.ingest(r)
            r=copy.deepcopy(self.record);r['provenance']={'value':value}
            with self.assertRaises(ValueError):
                self.store.ingest(r)


if __name__=='__main__':
    unittest.main()
