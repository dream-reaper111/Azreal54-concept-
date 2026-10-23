"""Installer CLI regression checks; all execution and hardware calls are mocked."""
import contextlib
import io
import json
import sys
import unittest
from unittest.mock import patch

import setup_lab


class SetupCliTests(unittest.TestCase):
    def test_setup_slm_import_does_not_download_or_configure_storage(self):
        import importlib
        import setup_slm
        with patch.object(setup_slm.storage_paths,'configure_cache_environment') as configure,patch('huggingface_hub.snapshot_download') as download:
            importlib.reload(setup_slm)
        configure.assert_not_called()
        download.assert_not_called()

    def setUp(self):
        self.stdout = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.stdout))
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))
        self.select = self.enterContext(patch.object(setup_lab, 'select_runtime', return_value='podman'))
        self.execute = self.enterContext(patch.object(setup_lab, 'execute'))
        self.probe = self.enterContext(patch.object(setup_lab, 'gpu_container_preflight'))
        self.report = self.enterContext(patch.object(setup_lab, 'write_verification_report'))
        self.rootless = self.enterContext(patch.object(setup_lab, 'record_rootless_preflight', return_value={'status': 'fixture_passed'}))
        self.process = self.enterContext(patch.object(setup_lab.subprocess, 'run',
            side_effect=AssertionError('CLI test attempted a real command')))

    def invoke(self, *arguments):
        with patch.object(sys, 'argv', ['setup_lab.py', *arguments]):
            setup_lab.main()

    def test_default_entry_point_has_complete_namespace(self):
        with patch.object(setup_lab, 'plan', return_value=[]) as plan:
            self.invoke()
        self.assertEqual(plan.call_args.args[:3], (True, True, False))
        self.execute.assert_called_once()
        self.assertFalse(self.execute.call_args.kwargs['gpu'])
        self.probe.assert_not_called()

    def test_run_sh_default_arguments_can_be_planned_without_execution(self):
        self.invoke('--runtime', 'podman', '--install', '--build', '--start', '--verify', '--plan')
        result = json.loads(self.stdout.getvalue())
        self.assertEqual(result['execution'], 'none')
        self.assertFalse(result['gpu_inference_verification'])
        self.assertTrue(any('up' in command for command in result['commands']))
        self.execute.assert_not_called()
        self.probe.assert_not_called()
        self.process.assert_not_called()
        self.report.assert_not_called()

    def test_gpu_preflight_plan_does_not_probe_or_deploy(self):
        self.invoke('--runtime', 'podman', '--gpu-preflight', '--plan')
        result = json.loads(self.stdout.getvalue())
        self.assertEqual(result['execution'], 'none')
        self.assertFalse(result['configuration_changed'])
        self.select.assert_called_once_with('podman', verify=False)
        self.probe.assert_not_called()
        self.execute.assert_not_called()
        self.report.assert_not_called()

    def test_gpu_preflight_dispatches_only_to_mocked_probe(self):
        self.probe.return_value = {'status': 'passed'}
        self.invoke('--runtime', 'podman', '--gpu-preflight')
        self.probe.assert_called_once_with('podman')
        self.assertEqual(self.report.call_args.args[0]['status'], 'gpu_preflight_passed')
        self.execute.assert_not_called()
        self.process.assert_not_called()

    def test_gpu_verification_plan_enables_cuda_and_inference(self):
        self.invoke('--runtime', 'podman', '--start', '--verify-gpu', '--plan')
        result = json.loads(self.stdout.getvalue())
        self.assertTrue(result['gpu_inference_verification'])
        self.assertTrue(result['gpu_runtime_preflight_required'])
        self.assertTrue(result['slm_inference_verification'])
        self.assertTrue(any(str(setup_lab.PODMAN_GPU_COMPOSE) in c for c in result['commands']))
        self.execute.assert_not_called()
        self.probe.assert_not_called()

    def test_gpu_verification_is_forwarded_to_mocked_executor(self):
        with patch.object(setup_lab, 'plan', return_value=[]):
            self.invoke('--runtime', 'podman', '--start', '--verify-gpu')
        self.execute.assert_called_once()
        self.assertTrue(self.execute.call_args.args[3])  # verify
        self.assertTrue(self.execute.call_args.args[4])  # verify_model
        self.assertTrue(self.execute.call_args.kwargs['gpu'])
        self.process.assert_not_called()

    def test_invalid_preflight_and_verification_combinations_fail_before_runtime(self):
        combinations = (
            ('--preflight', '--gpu-preflight'),
            ('--gpu-preflight', '--storage-check'),
            ('--gpu-preflight', '--build'),
            ('--gpu-preflight', '--start'),
            ('--gpu-preflight', '--gpu'),
            ('--gpu-preflight', '--verify-gpu'),
            ('--preflight', '--start'),
            ('--verify-gpu',),
            ('--verify-gpu', '--build'),
        )
        for arguments in combinations:
            with self.subTest(arguments=arguments), self.assertRaises(SystemExit) as error:
                self.invoke(*arguments, '--plan')
            self.assertEqual(error.exception.code, 2)
        self.select.assert_not_called()
        self.execute.assert_not_called()
        self.probe.assert_not_called()
        self.process.assert_not_called()


if __name__ == '__main__':
    unittest.main()
