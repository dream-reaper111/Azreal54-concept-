"""Installer contracts use dry plans and a harmless real child, never pip/Docker."""
from datetime import datetime,timezone,timedelta
import ast
import contextlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import os
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
from installation import Installation
import setup_lab
import healthcheck
import writable_layer_audit


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.setup=Installation(Path(__file__).parent,Path(self.tmp.name)/'queue')

    def request(self):return self.setup.request({'operation':'install_and_build','confirmed':True})

    def test_plan_has_fixed_dependencies_and_container_build_without_execution(self):
        with patch.object(setup_lab,'select_runtime',return_value='docker'):
            commands=setup_lab.plan(True,True,True,runtime='docker')
        self.assertTrue(any('requirements-runtime.txt' in ' '.join(c) for c in commands))
        self.assertTrue(any(Path(command[0]).name=='docker' and command[1:2]==['compose'] and command[-1:] == ['build'] for command in commands))
        compose_up=[command for command in commands if Path(command[0]).name=='docker' and command[1:2]==['compose'] and 'up' in command]
        self.assertEqual([command[command.index('-d')+2:] for command in compose_up],[['tools','imports','web-lab','external-tools'],['dashboard'],['frontend']])
        self.assertTrue(all(command[command.index('-d')+1]=='--no-recreate' for command in compose_up))
        self.assertTrue(any(Path(command[0]).name=='docker' and command[1:3]==['image','inspect'] and command[-1]=='localhost/azrael54-dashboard:latest' for command in commands))
        with patch.object(setup_lab,'select_runtime',return_value='podman'):
            podman_commands=setup_lab.plan(False,True,True,runtime='podman')
        self.assertTrue(any(Path(command[0]).name=='podman' and command[1:2]==['compose'] and command[-1:] == ['build'] for command in podman_commands))
        podman_up=[command for command in podman_commands if command[1:2]==['compose'] and 'up' in command]
        self.assertEqual([command[command.index('-d')+2:] for command in podman_up],[['tools','imports','web-lab','external-tools'],['dashboard'],['frontend']])
        self.assertTrue(all(command[command.index('-d')+1]=='--no-recreate' for command in podman_up))
        self.assertTrue(any(command[:3]==['podman','image','exists'] and command[-1]=='localhost/azrael54-external-tools:latest' for command in podman_commands))
        result=subprocess.run([sys.executable,str(Path(setup_lab.__file__)),'--install','--build','--plan'],capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(result.stdout)['execution'],'none')

    def test_gpu_plan_uses_cuda_overlay_and_recreation_is_explicit(self):
        with patch.object(setup_lab,'select_runtime',return_value='podman'):
            commands=setup_lab.plan(False,True,True,runtime='podman',gpu=True,recreate=True)
        compose_commands=[command for command in commands if command[1:2]==['compose']]
        self.assertTrue(all(str(setup_lab.PODMAN_GPU_COMPOSE) in command for command in compose_commands))
        up=[command for command in compose_commands if 'up' in command]
        self.assertEqual([command[command.index('-d')+1] for command in up],['--force-recreate','--force-recreate','--force-recreate'])
        recreated=[service for command in up for service in command[command.index('-d')+2:]]
        self.assertCountEqual(recreated,['tools','imports','web-lab','external-tools','dashboard','frontend'])
        self.assertFalse(any(any(arg in {'down','rm','volume','system'} for arg in command) for command in commands))
        self.assertTrue(any(command[-1:] == ['build'] for command in compose_commands))
        self.assertIn('whl/cu128',setup_lab.PODMAN_GPU_COMPOSE.read_text())

    def test_start_and_recreation_stop_before_execute_when_keep_id_preflight_fails(self):
        argv=[str(Path(setup_lab.__file__)),'--runtime','podman','--build','--start',
              '--recreate-project-containers','--verify','--verify-slm']
        with patch.object(setup_lab,'select_runtime',return_value='podman'), \
             patch.object(setup_lab,'record_rootless_preflight',side_effect=RuntimeError('keep-id failed')), \
             patch.object(setup_lab,'execute') as execute, patch.object(sys,'argv',argv):
            with self.assertRaisesRegex(RuntimeError,'keep-id failed'):setup_lab.main()
        execute.assert_not_called()

    def test_keep_id_failure_hypothesis_does_not_blame_storage_bind_mount(self):
        checks=[{'check':'simple_rootless','status':'passed'},
                {'check':'keep_id_rootless','status':'failed','error':'crun: make merged private: Permission denied'}]
        diagnostics=[{'diagnostic':'keep_id_graphroot_traversal_candidates',
                      'container_root_host_uid_candidate':100000,'container_root_host_gid_candidate':100000,
                      'ancestors_without_candidate_traverse_access':[{'path':'/home/deadbyte'}]}]
        hypothesis=setup_lab.preflight_hypothesis(checks,diagnostics)
        self.assertIn('isolated to keep-id startup',hypothesis)
        self.assertIn('graphroot ancestor traversal',hypothesis)
        self.assertIn('setfacl -m u:100000:x /home/deadbyte',hypothesis)
        self.assertIn('chmod o+x /home/deadbyte',hypothesis)
        self.assertIn('broader',hypothesis)
        self.assertIn('Advisory only',hypothesis)

    def test_preflight_hypothesis_reports_all_checks_passed(self):
        checks=[{'check':'simple_rootless','status':'passed'},
                {'check':'keep_id_rootless','status':'passed'},
                {'check':'azrael_storage_keep_id_rw','status':'passed'}]
        self.assertEqual(setup_lab.preflight_hypothesis(checks,[]),'All preflight checks passed.')

    def test_timed_phase_records_success_and_failure(self):
        report={'timings':{'pull':{'status':'not_run','elapsed_seconds':None,'segments':[]}}}
        with patch.object(setup_lab,'write_verification_report'):
            self.assertEqual(setup_lab._run_timed_phase(report,'pull','registry images',lambda:'ok'),'ok')
            self.assertEqual(report['timings']['pull']['status'],'passed')
            self.assertEqual(report['timings']['pull']['segments'][0]['status'],'passed')
            def fail():raise RuntimeError('registry failure')
            with self.assertRaisesRegex(RuntimeError,'registry failure'):
                setup_lab._run_timed_phase(report,'pull','retry',fail)
        self.assertEqual(report['timings']['pull']['status'],'failed')
        self.assertEqual(report['timings']['pull']['segments'][1]['error'],'registry failure')

    def test_verification_report_preserves_operator_host_diagnosis(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'DEPLOYMENT-VERIFICATION.json').write_text(json.dumps({'host_diagnosis':{'root_cause':'mapped path traversal'}}))
            with patch.object(setup_lab,'ROOT',root):
                setup_lab.write_verification_report({'status':'preflight_passed'})
            result=json.loads((root/'DEPLOYMENT-VERIFICATION.json').read_text())
        self.assertEqual(result['host_diagnosis']['root_cause'],'mapped path traversal')

    def test_gpu_selection_defaults_to_rtx_3080_and_allows_override(self):
        inventory=[{'index':'0','name':'NVIDIA GeForce RTX 3060 Ti','uuid':'GPU-a','memory_total':'8 GiB','compute_capability':'8.6'},
                   {'index':'1','name':'NVIDIA GeForce RTX 5060','uuid':'GPU-b','memory_total':'8 GiB','compute_capability':'12.0'},
                   {'index':'2','name':'NVIDIA GeForce RTX 3080','uuid':'GPU-c','memory_total':'10 GiB','compute_capability':'8.6'}]
        with patch.object(setup_lab,'host_gpu_inventory',return_value=inventory),patch.dict(os.environ,{},clear=True):
            self.assertEqual(setup_lab.select_gpu_device()['selector'],'2')
        with patch.object(setup_lab,'host_gpu_inventory',return_value=inventory),patch.dict(os.environ,{'AZRAEL_GPU_DEVICE':'1'}):
            selection=setup_lab.select_gpu_device()
        self.assertEqual(selection['devices'][0]['name'],'NVIDIA GeForce RTX 5060')

    def test_compose_healthcheck_test_arguments_avoid_shell_sensitive_characters(self):
        compose=(Path(setup_lab.__file__).parent/'compose.yaml').read_text()
        dashboard=compose[compose.index('  dashboard:'):compose.index('  tools:')]
        self.assertIn('AZRAEL_TMP_DIR: /var/lib/azrael54/tmp',dashboard)
        tests=[ast.literal_eval(value) for value in re.findall(r'^\s*test:\s*(\[.*\])\s*$',compose,re.M)]
        self.assertEqual(len(tests),6)
        for test in tests:
            self.assertEqual(test[0],'CMD')
            for argument in test:
                self.assertFalse(any(character in argument for character in '();\'"'),msg=f'unsafe healthcheck argument: {argument!r}')
        self.assertEqual(tests[0],['CMD','/app/.slm-venv/bin/python','/app/healthcheck.py'])
        compose_js=compose[compose.index('  web-lab:'):compose.index('  external-tools:')]
        self.assertIn('./healthcheck.js:/healthcheck.js:ro',compose_js)
        self.assertIn('${AZRAEL_WEB_LAB_SHELL:-/usr/bin/busybox}:/bin/sh:ro',compose_js)
        self.assertIn('${AZRAEL_JUICE_SHOP_FTP_ROOT:-/data/work/azrael54/juice-shop-ftp}:/juice-shop/ftp:rw',compose_js)
        self.assertIn('${AZRAEL_JUICE_SHOP_CSAF_ROOT:-/data/work/azrael54/juice-shop-csaf}:/juice-shop/.well-known/csaf:rw',compose_js)
        self.assertIn('${AZRAEL_JUICE_SHOP_FRONTEND_ROOT:-/data/work/azrael54/juice-shop-frontend}:/juice-shop/frontend/dist/frontend:rw',compose_js)
        self.assertIn('${AZRAEL_JUICE_SHOP_I18N_ROOT:-/data/work/azrael54/juice-shop-i18n}:/juice-shop/i18n:rw',compose_js)
        self.assertEqual(tests[3],['CMD','/healthcheck.js'])
        self.assertEqual(tests[5],['CMD','/usr/local/bin/healthcheck-frontend'])
        expected={'dashboard':('30s','5s','4','120s'),'tools':('30s','5s','3','5s'),
                  'imports':('30s','5s','3','5s'),'web-lab':('30s','5s','4','60s'),
                  'external-tools':('30s','5s','3','5s'),'frontend':('30s','5s','4','10s')}
        for service,settings in expected.items():
            block=compose[compose.index(f'  {service}:'):]
            next_service=re.search(r'^  [a-z][a-z-]*:',block[1:],re.M)
            if next_service:block=block[:next_service.start()+1]
            self.assertIn(f'interval: {settings[0]}',block)
            self.assertIn(f'timeout: {settings[1]}',block)
            self.assertIn(f'retries: {settings[2]}',block)
            self.assertIn(f'start_period: {settings[3]}',block)
        js=(Path(setup_lab.__file__).parent/'healthcheck.js').read_text()
        self.assertIn('http://127.0.0.1:3000/',js)
        self.assertIn('request.setTimeout(3000',js)
        import storage_paths
        self.assertIn('juice-shop-ftp',storage_paths.PRIVATE_DIRS)
        self.assertIn('juice-shop-csaf',storage_paths.PRIVATE_DIRS)
        self.assertIn('juice-shop-frontend',storage_paths.PRIVATE_DIRS)
        self.assertIn('juice-shop-i18n',storage_paths.PRIVATE_DIRS)

    def test_read_only_frontend_places_all_nginx_temp_files_under_tmp(self):
        nginx=(Path(setup_lab.__file__).parent/'container'/'nginx.conf').read_text()
        for directive in ('client_body_temp_path','proxy_temp_path','fastcgi_temp_path',
                          'uwsgi_temp_path','scgi_temp_path'):
            self.assertRegex(nginx,rf'(?m)^\s*{directive}\s+/tmp/')
        self.assertIn('resolver @AZRAEL_DNS_RESOLVERS@ valid=5s ipv6=off',nginx)
        self.assertEqual(nginx.count('proxy_pass http://$dashboard_service'),2)

    def test_python_healthcheck_preserves_url_and_three_second_timeout(self):
        response=MagicMock()
        response.__enter__.return_value.status=200
        with patch.object(healthcheck,'urlopen',return_value=response) as request:
            self.assertEqual(healthcheck.main(['healthcheck.py','8791']),0)
        request.assert_called_once_with('http://127.0.0.1:8791/healthz',timeout=3)

    def test_podman_readiness_runs_declared_healthcheck_when_monitor_is_unscheduled(self):
        calls=[]
        def fake_run(command,**kwargs):
            calls.append(command)
            if command[1:3]==['ps','-aq']:
                return subprocess.CompletedProcess(command,0,'container-id\n','')
            if command[1:3]==['healthcheck','run']:
                return subprocess.CompletedProcess(command,0,'','')
            if command[1:3]==['inspect','--format']:
                return subprocess.CompletedProcess(command,0,'running|healthy\n','')
            raise AssertionError(command)
        with patch.object(setup_lab.shutil,'which',return_value='/usr/bin/podman'), \
             patch.object(setup_lab.subprocess,'run',side_effect=fake_run):
            state=setup_lab.wait_for_services_healthy('podman',['tools'],timeout=1)
        self.assertEqual(state['tools'],'running|healthy')
        self.assertTrue(any(command[1:3]==['healthcheck','run'] for command in calls))

    def test_writable_layer_audit_skips_never_started_containers(self):
        result=writable_layer_audit.audit_diff('0001-01-01T00:00:00Z','C /etc\nA /app/x\n')
        self.assertEqual(result['status'],'skipped_never_started')
        self.assertEqual(result['unexpected_entries'],[])
        check=subprocess.run([sys.executable,str(Path(writable_layer_audit.__file__)),
                              '0001-01-01T00:00:00Z','--started-only'],
                             capture_output=True,text=True,check=True)
        self.assertEqual(check.stdout.strip(),'never_started')

    def test_writable_layer_audit_ignores_only_podman_injected_etc_entries(self):
        result=writable_layer_audit.audit_diff('2026-10-20T12:00:00Z',
            'C /etc\nA /etc/hosts\nC /etc/resolv.conf\nA /etc/hostname\n')
        self.assertEqual(result['status'],'clean')
        self.assertEqual(len(result['ignored_entries']),4)

    def test_writable_layer_audit_refuses_application_layer_changes(self):
        result=writable_layer_audit.audit_diff('2026-10-20T12:00:00Z','A /app/x\nC /etc\n')
        self.assertEqual(result['status'],'blocked')
        self.assertEqual(result['unexpected_entries'],['A /app/x'])

    def test_gpu_preflight_fails_when_nvidia_ctk_is_missing_and_advises_only(self):
        host={'host_gpu_detected':True,'nvidia_container_toolkit':False,
              'nvidia_cdi':{'status':'not_available','devices':[]}}
        with patch.object(setup_lab,'gpu_disk_space_preflight',return_value={'status':'passed'}), \
             patch.object(setup_lab,'gpu_status',return_value=host):
            with self.assertRaisesRegex(RuntimeError,'nvidia-ctk is missing') as error:
                setup_lab.gpu_container_preflight('podman')
        message=str(error.exception)
        self.assertIn('Install nvidia-container-toolkit',message)
        self.assertIn('sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml',message)
        self.assertIn('after NVIDIA driver updates',message)
        self.assertIn('Advisory only',message)

    def test_gpu_preflight_fails_when_cdi_has_no_nvidia_gpu_devices(self):
        host={'host_gpu_detected':True,'nvidia_container_toolkit':True,
              'nvidia_cdi':{'status':'failed','devices':[],'error':'no nvidia.com/gpu devices'}}
        with patch.object(setup_lab,'gpu_disk_space_preflight',return_value={'status':'passed'}), \
             patch.object(setup_lab,'gpu_status',return_value=host):
            with self.assertRaisesRegex(RuntimeError,'NVIDIA CDI is missing or unusable') as error:
                setup_lab.gpu_container_preflight('podman')
        self.assertIn('sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml',str(error.exception))

    def test_gpu_preflight_probe_uses_selected_device_and_keep_id(self):
        device={'index':'2','name':'NVIDIA GeForce RTX 3080','uuid':'GPU-c',
                'memory_total':'10 GiB','compute_capability':'8.6'}
        host={'host_gpu_detected':True,'nvidia_container_toolkit':True,
              'nvidia_cdi':{'status':'passed','devices':['nvidia.com/gpu=2']}}
        result=SimpleNamespace(returncode=0,stdout='NVIDIA GeForce RTX 3080\n',stderr='')
        with patch.object(setup_lab,'gpu_disk_space_preflight',return_value={'status':'passed'}), \
             patch.object(setup_lab,'gpu_status',return_value=host), \
             patch.object(setup_lab,'select_gpu_device',return_value={'selector':'2','devices':[device]}), \
             patch.object(setup_lab.shutil,'which',return_value='/usr/bin/podman'), \
             patch.object(setup_lab.subprocess,'run',return_value=result) as run:
            report=setup_lab.gpu_container_preflight('podman')
        command=run.call_args.args[0]
        self.assertIn('--userns',command)
        self.assertEqual(command[command.index('--userns')+1],'keep-id')
        self.assertEqual(command[command.index('--device')+1],'nvidia.com/gpu=2')
        self.assertIn('docker.io/library/ubuntu:24.04',command)
        self.assertEqual(command[-1],'nvidia-smi')
        self.assertEqual(report['podman_keep_id_probe'],'passed')

    def test_gpu_preflight_accepts_a_stable_uuid_selector(self):
        device={'index':'1','name':'NVIDIA GeForce RTX 5060',
                'uuid':'GPU-5aa46030-9e89-432f-ecfe-90daf9d56e30',
                'memory_total':'8151 MiB','compute_capability':'12.0'}
        host={'host_gpu_detected':True,'nvidia_container_toolkit':True,
              'nvidia_cdi':{'status':'passed','devices':['nvidia.com/gpu='+device['uuid']]}}
        result=SimpleNamespace(returncode=0,stdout='NVIDIA GeForce RTX 5060\n',stderr='')
        with patch.object(setup_lab,'gpu_disk_space_preflight',return_value={'status':'passed'}), \
             patch.object(setup_lab,'gpu_status',return_value=host), \
             patch.object(setup_lab,'host_gpu_inventory',return_value=[device]), \
             patch.object(setup_lab.shutil,'which',return_value='/usr/bin/podman'), \
             patch.object(setup_lab.subprocess,'run',return_value=result) as run:
            report=setup_lab.gpu_container_preflight('podman',device_selector=device['uuid'])
        command=run.call_args.args[0]
        self.assertEqual(command[command.index('--device')+1],
                         'nvidia.com/gpu='+device['uuid'])
        self.assertEqual(report['selected_host_device']['uuid'],device['uuid'])

    def test_gpu_disk_gate_stops_below_configured_graphroot_reserve(self):
        low_space=SimpleNamespace(total=100*1024**3,used=50*1024**3,free=59*1024**3)
        with patch.object(setup_lab,'container_graphroot',return_value=Path('/home/user/.local/share/containers/storage')), \
             patch.object(setup_lab.shutil,'disk_usage',return_value=low_space), \
             contextlib.redirect_stderr(io.StringIO()) as warning:
            with self.assertRaisesRegex(RuntimeError,'60 GiB is required') as error:
                setup_lab.gpu_disk_space_preflight('podman')
        self.assertIn('Moving graphroot to /data/work requires the same mapped-ID ancestor-traversal access',str(error.exception))
        self.assertIn('/home/user/.local/share/containers/storage',str(error.exception))
        self.assertIn('WARNING:',warning.getvalue())

    def test_gpu_preflight_failure_stops_before_build_or_recreation(self):
        with patch.object(setup_lab.os,'getuid',return_value=1000), \
             patch.object(setup_lab,'write_verification_report'), \
             patch.object(setup_lab,'runtime_probe',return_value={'rootless':True}), \
             patch.object(setup_lab,'gpu_container_preflight',side_effect=RuntimeError('CDI missing')), \
             patch.object(setup_lab.subprocess,'run') as run:
            with self.assertRaisesRegex(RuntimeError,'CDI missing'):
                setup_lab.execute([['podman-compose','build']],'podman',gpu=True)
        run.assert_not_called()

    def test_confirmation_unknown_command_replay_and_catalog_binding(self):
        for value in ({'operation':'shell','confirmed':True},{'operation':'install_and_build','confirmed':False},{'operation':'install_and_build','confirmed':True,'command':'id'}):
            with self.assertRaises(ValueError):self.setup.request(value)
        request=self.request()
        self.assertFalse(self.setup.status()['runner_active'])
        with self.assertRaises(ValueError):self.request()
        with patch.object(self.setup,'catalog',return_value='changed'):
            result=self.setup.run_one(request['id'])
        self.assertEqual(result['status'],'rejected')
        with self.assertRaises(ValueError):self.setup.run_one(request['id'])
        with self.assertRaises(ValueError):self.setup.details('../outside')

    def test_expiry_and_safe_real_child_retention(self):
        request=self.request();path=self.setup.root/request['id']/'status.json'
        request['requested_at']=(datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat();self.setup._write(path,request)
        with patch('installation.subprocess.Popen',side_effect=AssertionError('Expired request must not execute')):
            self.assertEqual(self.setup.run_one(request['id'])['status'],'expired')
        request=self.request();real_popen=subprocess.Popen;seen=[]
        def child(command,**kwargs):
            seen.append(command)
            return real_popen([sys.executable,'-c','print("explicit harmless installer test fixture")'],**kwargs)
        with patch('installation.subprocess.Popen',side_effect=child):result=self.setup.run_one(request['id'])
        self.assertEqual(result['status'],'completed')
        self.assertEqual(seen[0][2:],['--runtime','auto','--install','--build','--start','--verify','--verify-slm','--verify-providers','--non-interactive'])
        self.assertIn('harmless installer test fixture',self.setup.details(request['id'])['output_tail'])
        self.assertEqual((self.setup.root/request['id']/'output.log').stat().st_mode&0o777,0o600)


if __name__=='__main__':unittest.main()
