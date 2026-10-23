"""Real CPU jobs and isolated state exercise the managed training boundary."""
import contextlib
import io
import json
import os
import sys
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aztreal_training import cli,datasets,jobs,registry,resources,tui
from aztreal_training.store import ROOT,folder,read,write,sha,state_root


class TrainingTests(unittest.TestCase):
    def setUp(self):
        base=Path(tempfile.gettempdir())
        if not base.resolve().is_relative_to(ROOT):base=ROOT/'recovery/final-verification/scratch'
        base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base,prefix='training-test-');self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'AZTREAL_STATE_DIR':str(self.root/'state'),'PYTHONDONTWRITEBYTECODE':'1'})
        self.env.start();self.addCleanup(self.env.stop);self.addCleanup(self.temp.cleanup)

    def dataset(self,kind='classifier',approve=True):
        p=self.root/'input.jsonl'
        if kind=='classifier':rows=[{'text':f'Explicit synthetic case {i} category {i%2}','label':'benign' if i%2 else 'potential_secret'} for i in range(40)]
        else:rows=[{'instruction':f'Explicit coding fixture {i}','response':'def add(a,b): return a+b'} for i in range(6)]
        p.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        d=datasets.import_data(p,kind,'local authorized test fixture','CC0-1.0','yes',approve,'fixture operator')
        datasets.split(d['id']);return d['id']

    def config(self,**changes):return dict({'model':'secret-classifier','backend':'local','epochs':1,'max_steps':1},**changes)

    def test_all_command_parsers_have_help(self):
        commands=[['training'],['models','list'],['models','inspect'],['datasets','import'],['datasets','list'],
            ['datasets','inspect'],['datasets','validate'],['datasets','split'],['gpu','list'],['gpu','monitor']]
        commands +=[['training',n] for n in ['preflight','start','status','logs','stop','resume','evaluate','checkpoints','promote','rollback']]
        for command in commands:
            with self.subTest(command=command),contextlib.redirect_stdout(io.StringIO()),self.assertRaises(SystemExit) as e:
                cli.parser().parse_args(command+['--help'])
            self.assertEqual(e.exception.code,0)

    def test_registry_and_noninteractive_menu_initialize(self):
        self.assertIn('coding-slm',{r['id'] for r in registry.models()})
        with patch('sys.stdin.isatty',return_value=False):snapshot=tui.launch()
        self.assertEqual(snapshot['jobs'],[]);self.assertIn('gpu',snapshot)
        self.assertTrue(snapshot['cpu']['available']);self.assertGreaterEqual(snapshot['cpu']['available_ram_bytes'],0)

    def test_training_runtime_requires_ready_marker_and_supports_explicit_cpu(self):
        from aztreal_training.runtime import interpreter
        with patch.dict(os.environ,{'AZTREAL_PYTHON':''}):
            self.assertEqual(interpreter(self.root),self.root/'.slm-venv/bin/python')
            python=self.root/'.training-venv/bin/python';python.parent.mkdir(parents=True);python.touch();python.chmod(0o700)
            self.assertEqual(interpreter(self.root),self.root/'.slm-venv/bin/python')
            marker=python.parent.parent/'aztreal-runtime.json';marker.write_text('{"status":"ready"}')
            self.assertEqual(interpreter(self.root),python)
        original=str(ROOT/'.slm-venv/bin/python')
        with patch.dict(os.environ,{'AZTREAL_PYTHON':original}):self.assertEqual(interpreter(self.root),Path(original))
        with patch.dict(os.environ,{'AZTREAL_PYTHON':'relative-python'}):
            with self.assertRaisesRegex(ValueError,'absolute executable'):interpreter(self.root)

    def test_cuda_provisioner_inventories_legacy_egg_metadata(self):
        from setup_training_cuda import installed_roots
        package=self.root/'legacy';package.mkdir();info=self.root/'legacy-1.0.egg-info';info.mkdir()
        dist=SimpleNamespace(files=None,read_text=lambda name:'legacy\n',locate_file=lambda name:self.root/name,
                             _path=info,metadata={'Name':'legacy'})
        self.assertEqual(installed_roots(dist),{'legacy','legacy-1.0.egg-info'})
        dist.read_text=lambda name:''
        with self.assertRaisesRegex(ValueError,'no package file inventory'):installed_roots(dist)

    def test_schema_conflicts_duplicates_and_secret_rejection(self):
        p=self.root/'data.jsonl'
        p.write_text('\n'.join(json.dumps(r) for r in [{'text':'same','label':'a'},{'text':'same','label':'a'}]))
        report,rows=datasets.validate(p);self.assertTrue(report['valid']);self.assertEqual(report['duplicates_removed'],1)
        p.write_text('\n'.join(json.dumps(r) for r in [{'text':'same','label':'a'},{'text':'same','label':'b'}]))
        self.assertFalse(datasets.validate(p)[0]['valid'])
        p.write_text(json.dumps({'text':'-----BEGIN PRIVATE KEY----- fixture','label':'a'}))
        self.assertEqual(datasets.validate(p)[0]['sensitive_rows'],1)
        p.write_bytes(b'\xff')
        with self.assertRaises(ValueError):datasets.validate(p)

    def test_json_and_csv_dataset_formats(self):
        p=self.root/'examples.json'
        p.write_text(json.dumps([{'prompt':'Add two integers','output':'def add(a,b): return a+b'}]))
        self.assertEqual(datasets.validate(p)[0]['kind'],'slm')
        p=self.root/'examples.csv'
        p.write_text('description,type\nSynthetic local parser case,local\nSynthetic remote parser case,remote\n')
        report,rows=datasets.validate(p)
        self.assertTrue(report['valid']);self.assertEqual(report['kind'],'classifier');self.assertEqual(len(rows),2)

    def test_admission_and_split_hash_guards(self):
        version=self.dataset(approve=False)
        with self.assertRaisesRegex(ValueError,'not admitted'):datasets.admitted(version)
        p=folder('datasets')/version/'records.json';p.write_text('[]')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):datasets.inspect(version)

    def test_explicit_later_admission_does_not_invent_new_source_metadata(self):
        version=self.dataset(approve=False)
        admitted=datasets.import_data(self.root/'input.jsonl','classifier','local authorized test fixture','CC0-1.0','yes',True,'fixture operator')
        self.assertEqual(admitted['id'],version);self.assertTrue(admitted['approved'])
        self.assertEqual(datasets.admitted(version)[0]['source'],'local authorized test fixture')

    def test_split_overlap_is_rejected_even_with_updated_file_hash(self):
        version=self.dataset();p=folder('datasets')/version;split=read(p/'split.json')
        split['validation'].append(split['train'][0]);write(p/'split.json',split)
        manifest=read(p/'manifest.json');manifest['split']['sha256']=sha(p/'split.json');write(p/'manifest.json',manifest)
        with self.assertRaisesRegex(ValueError,'overlap'):datasets.admitted(version)

    def test_local_training_checkpoint_evaluation_selection_and_rollback(self):
        original=sha(ROOT/'models-more/secret.pt');version=self.dataset()
        job=jobs.start(self.config(),version);result=jobs.wait(job['id'],60)
        self.assertEqual(result['state'],'completed',result.get('error'))
        self.assertEqual(result['python_executable'],sys.executable)
        self.assertNotIn(job['id'],jobs._CHILDREN)
        evidence=result['execution_evidence']
        self.assertEqual(evidence['parameter_devices'],['cpu']);self.assertEqual(evidence['gradient_devices'],['cpu'])
        self.assertEqual(evidence['input_device'],'cpu');self.assertEqual(evidence['loss_device'],'cpu')
        self.assertTrue(evidence['optimizer_updated_parameters']);self.assertNotIn('cuda_span_ms',evidence)
        from aztreal_training.verify_cuda import cuda_execution
        self.assertFalse(cuda_execution(result,'GPU-fixture'))
        self.assertTrue(Path(result['checkpoint']).is_file());self.assertEqual(sha(ROOT/'models-more/secret.pt'),original)
        with self.assertRaisesRegex(ValueError,'evaluated'):registry.promote(job['id'],'secret-classifier')
        from aztreal_training.evaluation import evaluate
        metrics=evaluate(job['id']);self.assertIn('confusion_matrix',metrics);self.assertIn('rates',metrics)
        self.assertEqual(metrics['examples'],8)
        with self.assertRaises(ValueError):registry.promote(job['id'],'wrong-model')
        selection=registry.promote(job['id'],'secret-classifier');self.assertEqual(selection['job'],job['id'])
        rolled=registry.rollback('secret-classifier','secret-classifier');self.assertIsNone(rolled['selected'])
        self.assertEqual(sha(ROOT/'models-more/secret.pt'),original)

    def test_graceful_stop_and_real_optimizer_resume(self):
        job=jobs.start(self.config(epochs=2),self.dataset());jobs.stop(job['id'])
        paused=jobs.wait(job['id'],60);self.assertEqual(paused['state'],'paused',paused.get('error'))
        self.assertTrue(Path(paused['resume_checkpoint']).is_file())
        changed_device=dict(paused['preflight'],selected_gpu={'uuid':'GPU-different'})
        with patch('aztreal_training.resources.preflight',return_value=changed_device):
            with self.assertRaisesRegex(ValueError,'original assigned device'):jobs.resume(job['id'])
        resumed=jobs.resume(job['id']);done=jobs.wait(job['id'],60)
        self.assertEqual(done['state'],'completed',done.get('error'));self.assertEqual(done['epoch'],2)
        self.assertEqual(done['attempts'],2)

    def test_failed_driver_and_tampered_resume_are_detected(self):
        version=self.dataset();job=jobs.start(self.config(epochs=2),version);jobs.stop(job['id']);paused=jobs.wait(job['id'],60)
        Path(paused['resume_checkpoint']).write_bytes(b'isolated fixture corruption')
        with self.assertRaisesRegex(ValueError,'integrity'):jobs.resume(job['id'])

    def test_unavailable_backend_and_disk_preflight(self):
        self.assertFalse(resources.backend('kubernetes')['available'])
        with patch('aztreal_training.resources.shutil.disk_usage',return_value=type('Usage',(),{'free':1})()):
            result=resources.preflight(jobs.checked_config(self.config()))
        self.assertFalse(result['eligible']);self.assertTrue(any('disk' in x.lower() for x in result['errors']))

    def test_explicit_resource_confirmation_and_invalid_args(self):
        with self.assertRaisesRegex(ValueError,'resource-intensive'):jobs.checked_config(self.config(epochs=4))
        with self.assertRaises(ValueError):jobs.checked_config(self.config(batch_size=0))
        args=cli.parser().parse_args(['training','resume','--job','fixture','--epochs','4','--confirm-resource-intensive'])
        self.assertTrue(args.confirm_resource_intensive)
        with patch('aztreal_training.jobs.get',return_value={'config':self.config(),'dataset':'fixture'}),patch('aztreal_training.jobs.start') as start:
            jobs.resume('fixture',epochs=4,confirm_resource_intensive=True)
        self.assertTrue(start.call_args.args[0]['confirm_resource_intensive'])

    def test_single_device_reservation_and_stale_job_recovery(self):
        version=self.dataset();job=jobs.start(self.config(epochs=2),version)
        try:
            with self.assertRaisesRegex(ValueError,'reserved'):jobs.start(self.config(),version)
        finally:jobs.stop(job['id']);jobs.wait(job['id'],60)
        jobs.update(job['id'],state='training',driver_pid=99999999,driver_start='invalid')
        self.assertEqual(jobs.get(job['id'])['stage'],'driver_lost')

    def test_lora_updates_only_adapter_parameters(self):
        import torch
        from torch import nn
        from aztreal_training import lora
        net=nn.Module();net.q_proj=nn.Linear(4,4);original=net.q_proj.weight.detach().clone()
        lora.install(net,2);opt=torch.optim.AdamW([p for p in net.parameters() if p.requires_grad],lr=.01)
        loss=net.q_proj(torch.ones(2,4)).square().mean();loss.backward();opt.step()
        self.assertTrue(torch.equal(original,net.q_proj.base.weight));self.assertTrue(any(v.abs().sum()>0 for k,v in lora.adapter_state(net).items() if 'lora_b' in k))

    def test_stable_uuid_gpu_selection_uses_free_memory_not_a_pooled_total(self):
        devices=[{'uuid':'GPU-a','name':'RTX 5060','free_mib':7000,'total_mib':8000},
                 {'uuid':'GPU-b','name':'RTX 3080','free_mib':9000,'total_mib':10000}]
        self.assertEqual(resources.select_gpu(devices,'auto')['uuid'],'GPU-b')
        self.assertEqual(resources.select_gpu(devices,'GPU-a')['uuid'],'GPU-a')
        devices[1]['free_mib']=100
        self.assertEqual(resources.select_gpu(devices,'auto')['uuid'],'GPU-a')
        with self.assertRaises(ValueError):resources.select_gpu(devices,'auto',minimum_mib=12000)

    def test_generated_code_is_interpreted_without_execution(self):
        from aztreal_training.lora import safe_add_correctness
        self.assertTrue(safe_add_correctness('def add(a,b): return a+b'))
        self.assertFalse(safe_add_correctness('def add(a,b): return __import__("os").system("id")'))

    def test_cuda_pass_policy_rejects_incomplete_or_cpu_evidence(self):
        # These are fabricated policy inputs, not GPU execution evidence.
        import copy
        from aztreal_training.verify_cuda import cuda_execution
        ev={'parameter_devices':['cuda:0'],'gradient_devices':['cuda:0'],'input_device':'cuda:0',
            'target_device':'cuda:0','loss_device':'cuda:0','optimizer_updated_parameters':True,'cuda_span_ms':1.}
        record={'state':'completed','assigned_device':'GPU-fixture','actual_cuda_uuid':'GPU-fixture',
                'execution_evidence':ev,'step':1,'peak_gpu_memory_bytes':1024}
        self.assertTrue(cuda_execution(record,'GPU-fixture'))
        for key,value in [('input_device','cpu'),('gradient_devices',[]),('optimizer_updated_parameters',False),('cuda_span_ms',0)]:
            bad=copy.deepcopy(record);bad['execution_evidence'][key]=value
            self.assertFalse(cuda_execution(bad,'GPU-fixture'))
        self.assertFalse(cuda_execution(record,'GPU-other'))
        from aztreal_training.verify_cuda import sample_summary
        self.assertIsNone(sample_summary([])['peak_sampled_utilization_percent'])
        sampled=sample_summary([{'exit_code':0,'stdout':'GPU-e6a4de67-74d6-38f7-e185-214a092dd995, 100, 9000, 0'}])
        self.assertEqual(sampled['peak_sampled_utilization_percent'],0);self.assertEqual(sampled['sample_count'],1)


if __name__=='__main__':unittest.main(verbosity=2)
