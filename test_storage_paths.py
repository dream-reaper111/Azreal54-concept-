import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import storage_paths


class StoragePathsTests(unittest.TestCase):
    def test_preflight_creates_private_layout_and_removes_probe(self):
        with tempfile.TemporaryDirectory(prefix='azrael-storage-test-') as temporary:
            root=Path(temporary)/'store'
            report=storage_paths.prepare_storage(root)
            self.assertEqual(report['write_readback'],'passed')
            self.assertTrue(report['temporary_probe_removed'])
            self.assertEqual(root.stat().st_mode&0o777,0o700)
            self.assertTrue((root/'datasets').is_dir())
            self.assertTrue((root/'checkpoints').is_dir())
            self.assertFalse(list((root/'tmp').glob('.write-test-*')))

    def test_read_only_mount_fails_before_creating_storage(self):
        with tempfile.TemporaryDirectory(prefix='azrael-storage-test-') as temporary:
            root=Path(temporary)/'store'
            with patch('storage_paths.mount_for',return_value={'target':temporary,'options':['ro'],'read_only':True}):
                with self.assertRaisesRegex(PermissionError,'read-only mount'):
                    storage_paths.prepare_storage(root)
            self.assertFalse(root.exists())

    def test_dataset_lookup_prefers_shared_data_and_keeps_legacy_fallback(self):
        with tempfile.TemporaryDirectory(prefix='azrael-storage-test-') as temporary:
            base=Path(temporary);shared=base/'shared';legacy=base/'legacy';project=base/'project'
            (legacy/'reference.json').parent.mkdir(parents=True)
            (legacy/'reference.json').write_text('legacy')
            with patch.dict(os.environ,{'AZRAEL_STORAGE_ROOT':str(shared),'AZRAEL_LEGACY_DATASET_DIR':str(legacy)}):
                self.assertEqual(storage_paths.data_path(project,'reference.json'),legacy/'reference.json')
                (shared/'datasets').mkdir(parents=True)
                (shared/'datasets'/'reference.json').write_text('shared')
                self.assertEqual(storage_paths.data_path(project,'reference.json'),shared/'datasets'/'reference.json')
                with self.assertRaises(ValueError):storage_paths.data_path(project,'../escape.json')

    def test_checkpoint_writes_are_shared_but_existing_project_weights_remain_readable(self):
        with tempfile.TemporaryDirectory(prefix='azrael-storage-test-') as temporary:
            base=Path(temporary);project=base/'project';shared=base/'shared'
            legacy=project/'models-public'/'role.pt';legacy.parent.mkdir(parents=True);legacy.write_bytes(b'legacy')
            with patch.dict(os.environ,{'AZRAEL_STORAGE_ROOT':str(shared)}):
                self.assertEqual(storage_paths.checkpoint_file(project,'models-public','role.pt'),legacy)
                self.assertEqual(storage_paths.checkpoint_root(project,'models-public'),shared/'checkpoints'/'models-public')
                with self.assertRaises(ValueError):storage_paths.checkpoint_file(project,'models-public','../role.pt')


if __name__=='__main__':unittest.main()
