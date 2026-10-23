"""The one-command control plane is deterministic and refuses unsafe recreation."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parent
loader = importlib.machinery.SourceFileLoader('azraelctl_test_module', str(ROOT / 'azraelctl'))
spec = importlib.util.spec_from_loader(loader.name, loader)
azraelctl = importlib.util.module_from_spec(spec)
loader.exec_module(azraelctl)


class AzraelCtlTests(unittest.TestCase):
    def test_cdi_compatibility_spec_uses_v05_and_stable_uuid_names(self):
        source = '''---
cdiVersion: 0.5.0
kind: nvidia.com/gpu
devices:
    - name: "GPU-5AA46030-9E89-432F-ECFE-90DAF9D56E30"
      containerEdits: {}
'''
        converted = azraelctl.compatible_cdi_text(source)
        self.assertIn('GPU-5AA46030-9E89-432F-ECFE-90DAF9D56E30', converted)
        self.assertNotIn('additionalGids', converted)

    def test_readonly_cdi_converts_cuda_aliases_and_removes_noncompute_hooks(self):
        import yaml
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'libcuda.so.580.1').write_bytes(b'cuda-driver')
            create_link = {'hookName': 'createContainer', 'path': '/usr/bin/nvidia-cdi-hook',
                           'args': ['nvidia-cdi-hook', 'create-symlinks', '--link',
                                    'libcuda.so.580.1::/usr/lib/x86_64-linux-gnu/libcuda.so.1',
                                    '--link', '../card0::/dev/dri/by-path/pci-card']}
            source_spec = {
                'cdiVersion': '0.5.0', 'kind': 'nvidia.com/gpu',
                'devices': [{'name': 'GPU-5aa46030-9e89-432f-ecfe-90daf9d56e30', 'containerEdits': {
                    'deviceNodes': [{'path': '/dev/nvidia0', 'major': 195, 'permissions': 'rwm'},
                                    {'path': '/dev/dri/card0', 'major': 226, 'permissions': 'rwm'}],
                    'hooks': [{'hookName': 'createRuntime', 'path': '/usr/bin/nvidia-cdi-hook',
                               'args': ['nvidia-cdi-hook', 'apply-cuda-memory-limits']}, create_link]}}],
                'containerEdits': {'env': ['NVIDIA_VISIBLE_DEVICES=void'],
                    'hooks': [create_link,
                              {'hookName': 'createContainer', 'path': '/usr/bin/nvidia-cdi-hook',
                               'args': ['nvidia-cdi-hook', 'update-ldcache']},
                              {'hookName': 'createContainer', 'path': '/usr/bin/nvidia-cdi-hook',
                               'args': ['nvidia-cdi-hook', 'enable-cuda-compat']}],
                    'mounts': [{'hostPath': '/tmp/unused', 'containerPath': '/usr/bin/nvidia-smi',
                                'options': ['ro']}]} }
            converted = yaml.safe_load(azraelctl.compatible_cdi_text(yaml.safe_dump(source_spec), root))
            device = converted['devices'][0]['containerEdits']
            self.assertEqual([node['path'] for node in device['deviceNodes']], ['/dev/nvidia0'])
            self.assertEqual([hook['args'][1] for hook in device['hooks']], ['apply-cuda-memory-limits'])
            edits = converted['containerEdits']
            self.assertEqual([hook['args'][1] for hook in edits['hooks']], ['enable-cuda-compat'])
            self.assertEqual(edits['env'][-1], 'LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu')
            self.assertEqual(len(edits['mounts']), 1)
            mount = edits['mounts'][0]
            self.assertEqual(mount['hostPath'], str(root / 'libcuda.so.580.1'))
            self.assertEqual(mount['containerPath'], '/usr/lib/x86_64-linux-gnu/libcuda.so.1')
            self.assertIn('ro', mount['options'])

    def test_readonly_cdi_rejects_library_alias_escape_and_missing_files(self):
        import yaml
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for source_path in ('../../../../etc/passwd', 'missing.so'):
                spec_data = {'cdiVersion': '0.5.0', 'kind': 'nvidia.com/gpu',
                    'devices': [{'name': 'GPU-5aa46030-9e89-432f-ecfe-90daf9d56e30', 'containerEdits': {}}],
                    'containerEdits': {'hooks': [{'hookName': 'createContainer',
                        'path': '/usr/bin/nvidia-cdi-hook', 'args': ['nvidia-cdi-hook',
                        'create-symlinks', '--link', source_path + '::/usr/lib/x86_64-linux-gnu/libcuda.so.1']} ]}}
                with self.assertRaises(azraelctl.DeploymentError):
                    azraelctl.compatible_cdi_text(yaml.safe_dump(spec_data), root)

    def test_cdi_compat_generation_is_private_and_preserves_uuid_selection(self):
        source = '''---
cdiVersion: 0.5.0
kind: nvidia.com/gpu
devices:
    - name: "GPU-5AA46030-9E89-432F-ECFE-90DAF9D56E30"
      containerEdits: {}
'''
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            cdi_dir = runtime / 'cdi-compat'

            def generate(argv, **kwargs):
                Path(argv[-1]).write_text(source)
                return subprocess.CompletedProcess(argv, 0, '', '')

            with patch.object(azraelctl, 'RUNTIME', runtime), \
                    patch.object(azraelctl, 'CDI_COMPAT_DIR', cdi_dir), \
                    patch.object(azraelctl.shutil, 'which', return_value='/usr/bin/nvidia-ctk'), \
                    patch.object(azraelctl.subprocess, 'run', side_effect=generate), \
                    patch('setup_lab.host_gpu_inventory', return_value=[{'uuid': 'GPU-5aa46030-9e89-432f-ecfe-90daf9d56e30'}]), \
                    patch.object(azraelctl, 'note'), \
                    patch.dict(os.environ, {}, clear=False), \
                    patch.object(azraelctl, 'CDI_COMPAT_ACTIVE', False):
                report = azraelctl.ensure_cdi_compat_spec()
                self.assertTrue(azraelctl.CDI_COMPAT_ACTIVE)
                self.assertEqual(os.environ['AZRAEL_CDI_COMPAT_SPEC_DIR'], str(cdi_dir))

            spec = cdi_dir / 'nvidia.yaml'
            self.assertEqual(report['status'], 'passed')
            self.assertEqual(cdi_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual(spec.stat().st_mode & 0o777, 0o600)
            self.assertIn('GPU-5AA46030-9E89-432F-ECFE-90DAF9D56E30', spec.read_text())

    def test_gpu_podman_command_uses_private_cdi_namespace_only_when_enabled(self):
        command = ['podman', 'run', '--device', 'nvidia.com/gpu=GPU-abcd']
        with patch.object(azraelctl, 'CDI_COMPAT_ACTIVE', False):
            self.assertEqual(azraelctl.podman_compat_argv(command), command)
        with patch.object(azraelctl, 'CDI_COMPAT_ACTIVE', True), \
                patch.object(azraelctl, 'CDI_COMPAT_DIR', Path('/private/cdi')):
            wrapped = azraelctl.podman_compat_argv(command)
        self.assertIn('unshare', wrapped)
        self.assertIn(str(azraelctl.CDI_COMPAT_WRAPPER), wrapped)
        self.assertEqual(wrapped[-len(command):], command)

    def test_gpu_compose_uses_one_aggregate_cdi_hook_and_stable_uuid_visibility(self):
        devices=[{'uuid':'GPU-a','name':'NVIDIA GeForce RTX 3080'},
                 {'uuid':'GPU-b','name':'NVIDIA GeForce RTX 5060'}]
        with tempfile.TemporaryDirectory() as temporary, patch.object(
                azraelctl,'GPU_COMPOSE_FILE',Path(temporary)/'compose.gpu.yaml'):
            azraelctl.generate_gpu_compose(devices,devices[0])
            content=azraelctl.GPU_COMPOSE_FILE.read_text()
        self.assertEqual(content.count('nvidia.com/gpu='),1)
        self.assertIn('nvidia.com/gpu=all',content)
        self.assertIn('GPU-a,GPU-b',content)
        self.assertIn('LD_LIBRARY_PATH: "/usr/lib/x86_64-linux-gnu"',content)

    def test_cuda_probes_use_readonly_least_privilege_and_test_each_uuid(self):
        devices=[{'uuid':'GPU-a','name':'NVIDIA GeForce RTX 3080'},
                 {'uuid':'GPU-b','name':'NVIDIA GeForce RTX 5060'}]
        calls=[]
        def fake_run(command,**kwargs):
            calls.append(command)
            expected=next((part.split('=',1)[1] for part in command if part.startswith('AZRAEL_GPU_EXPECTED_UUIDS=')), '')
            rows=[{'uuid':uuid,'name':next(item['name'] for item in devices if item['uuid']==uuid),
                   'matrix_operation':'passed','training_forward_backward_optimizer_step':'passed'}
                  for uuid in expected.split(',')]
            payload=json.dumps({'status':'passed','devices':rows,'torch':'2.11.0+cu128','cuda_build':'12.8'})
            return subprocess.CompletedProcess(command,0,payload+'\n','')
        with patch.object(azraelctl,'run',side_effect=fake_run):
            per_gpu,multi=azraelctl.run_cuda_probe('image',devices,{})
        self.assertEqual([row['status'] for row in per_gpu],['passed','passed'])
        self.assertEqual(multi['status'],'passed')
        self.assertEqual(len(calls),3)
        for command in calls:
            self.assertIn('--read-only',command)
            self.assertIn('--cap-drop=ALL',command)
            self.assertIn('--security-opt',command)
            self.assertIn('no-new-privileges',command)
            self.assertIn('--network=none',command)

    def test_gpu_failure_rollback_restarts_only_dashboard_and_frontend(self):
        import setup_lab
        restarted=[]
        with patch.dict(os.environ,{},clear=False), \
             patch.object(azraelctl,'image_id',return_value='verified-cpu-image'), \
             patch.object(azraelctl,'run') as run, \
             patch.object(azraelctl,'write_compose_env',return_value={'AZRAEL_GPU_ENABLED':'false'}), \
             patch.object(azraelctl,'compose_environment',return_value={'PODMAN_COMPOSE_PROVIDER':'provider'}), \
             patch.object(azraelctl,'provider_executable',return_value='provider'), \
             patch.object(azraelctl,'compose_prefix',return_value=['podman','compose']), \
             patch.object(azraelctl,'run_compose_up',side_effect=lambda service,**kwargs:restarted.append(service)), \
             patch.object(setup_lab,'wait_for_services_healthy'), \
             patch.object(azraelctl,'verify_http_surface',return_value={'status':'passed'}), \
             patch.object(setup_lab,'verify_dashboard',return_value={'status':'passed'}), \
             patch.object(setup_lab,'verify_slm',return_value={'status':'passed','device':'cpu'}), \
             patch.object(setup_lab,'verify_internal_services',return_value={'status':'passed'}):
            report=azraelctl.restore_cpu_dashboard(8765,'juice-shop-snapshot',{},RuntimeError('CUDA service failed'))
        self.assertEqual(report['status'],'cpu_fallback')
        self.assertEqual(restarted,['dashboard','frontend'])
        self.assertEqual(run.call_args_list[0].args[0],
                         ['podman','tag','localhost/azrael54-dashboard:cpu-fallback','localhost/azrael54-dashboard:latest'])

    def test_verification_stage_retries_a_transient_cold_start_timeout(self):
        calls = []

        def operation():
            calls.append(True)
            if len(calls) == 1:
                raise TimeoutError('timed out')
            return {'status': 'passed'}

        with patch.object(azraelctl, 'note'), patch.object(azraelctl.time, 'sleep') as sleep:
            result = azraelctl.verification_stage('dashboard', operation)
        self.assertEqual(result, {'status': 'passed'})
        self.assertEqual(len(calls), 2)
        sleep.assert_called_once_with(2)

    def test_all_lifecycle_subcommands_have_help(self):
        commands = ('bootstrap', 'start', 'stop', 'restart', 'status', 'logs', 'doctor', 'verify', 'update')
        for command in commands:
            result = subprocess.run([str(ROOT / 'azraelctl'), command, '--help'],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, command)
            self.assertIn('usage:', result.stdout.lower())

    def test_dependency_detection_distinguishes_required_and_optional(self):
        def which(name):
            return {'python3': '/usr/bin/python3', 'git': None, 'podman': '/usr/bin/podman',
                    'podman-compose': '/usr/bin/podman-compose', 'curl': '/usr/bin/curl',
                    'nvidia-smi': None}.get(name)
        with patch.object(azraelctl.shutil, 'which', side_effect=which):
            report = azraelctl.dependency_report()
        self.assertEqual(report['missing_required'], ['git'])
        self.assertIsNone(report['optional']['nvidia-smi'])

    def test_environment_generation_is_idempotent_and_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.dict(os.environ, {'AZRAEL_STORAGE_ROOT': str(root / 'storage')}, clear=True), \
                    patch.object(azraelctl, 'RUNTIME', root), patch.object(azraelctl, 'ENV_FILE', root / 'compose.env'):
                first = azraelctl.write_compose_env('cpu', web_image='localhost/juice:preserved')
                content = (root / 'compose.env').read_text()
                second = azraelctl.write_compose_env('cpu', web_image='localhost/juice:preserved')
                self.assertEqual(first, second)
                self.assertEqual(content, (root / 'compose.env').read_text())
                self.assertEqual((root / 'compose.env').stat().st_mode & 0o777, 0o600)
                self.assertNotIn('TOKEN', content)
                shell = Path(first['AZRAEL_WEB_LAB_SHELL'])
                self.assertTrue(shell.is_file())
                self.assertEqual(shell.stat().st_mode & 0o777, 0o555)

    def test_persistent_juice_migration_backs_up_before_verified_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'; source.mkdir()
            target = root / 'persistent'; target.mkdir()
            for directory, marker in ((source, 'new state'), (target, 'old state')):
                with sqlite3.connect(directory / 'juiceshop.sqlite') as db:
                    db.execute('CREATE TABLE preservation(value TEXT)')
                    db.execute('INSERT INTO preservation VALUES(?)', (marker,))
            backup = root / 'backup'; backup.mkdir()
            result = azraelctl.backup_active_juice_shop(source, target, backup)
            self.assertTrue(result['preserved_existing'])
            self.assertEqual(result['prior_state_backup_verification'], 'passed')
            with sqlite3.connect(target / 'juiceshop.sqlite') as db:
                self.assertEqual(db.execute('SELECT value FROM preservation').fetchone()[0], 'new state')
            backup_copy=backup / 'important-files' / 'persistent-existing'
            with sqlite3.connect(backup_copy / 'juiceshop.sqlite') as db:
                self.assertEqual(db.execute('SELECT value FROM preservation').fetchone()[0], 'old state')

    def test_stopped_container_copy_normalizes_podman_mount_and_directory_layouts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            def fake_run(command, **kwargs):
                source=command[2].split(':',1)[1]
                stage=Path(command[3])
                child=stage/Path(source).name
                child.mkdir()
                if source.endswith('/data'):
                    with sqlite3.connect(child/'juiceshop.sqlite') as db:
                        db.execute('CREATE TABLE preserved(value TEXT)')
                        db.execute("INSERT INTO preserved VALUES('latest')")
                elif not source.endswith('/csaf'):
                    (child/'preserved.txt').write_text(source)
                return None
            with patch.object(azraelctl,'run',side_effect=fake_run):
                paths=azraelctl.copy_from_container('container-id',root,{})
            self.assertEqual(paths['sqlite_integrity'],'ok')
            self.assertEqual(paths['sqlite_tables'],1)
            self.assertEqual(paths['data'].name,'juice-shop-data')
            self.assertTrue((paths['data']/'juiceshop.sqlite').is_file())
            for key in ('logs','ftp','csaf','frontend','i18n'):
                self.assertTrue(paths[key].is_dir())
            self.assertTrue((paths['logs']/'preserved.txt').is_file())
            self.assertTrue((paths['ftp']/'preserved.txt').is_file())
            self.assertTrue((paths['frontend']/'preserved.txt').is_file())
            self.assertTrue((paths['i18n']/'preserved.txt').is_file())
            self.assertEqual(paths['csaf_file_count'],0)

    def test_runtime_seed_merge_preserves_image_assets_and_live_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            seed=root/'seed'; seed.mkdir(); (seed/'provider.json').write_text('image')
            current=root/'current'; current.mkdir(); (current/'live.txt').write_text('live')
            destination=root/'merged'
            result=azraelctl.merge_juice_shop_trees(seed,current,destination)
            self.assertEqual((result/'provider.json').read_text(),'image')
            self.assertEqual((result/'live.txt').read_text(),'live')

    def test_recreation_guard_blocks_unbacked_application_changes(self):
        item = {'Id': 'abc', 'State': {'StartedAt': '2026-10-20T10:00:00Z'}}
        result = subprocess.CompletedProcess(['podman', 'diff'], 0, 'A /app/private.sqlite\n', '')
        blocked = {'status': 'blocked', 'unexpected_entries': ['A /app/private.sqlite']}
        with patch.object(azraelctl, 'run', return_value=result), \
             patch('writable_layer_audit.audit_diff', return_value=blocked):
            with self.assertRaisesRegex(azraelctl.DeploymentError, 'unbacked writable-layer changes'):
                azraelctl.audit_recreation('tools', item, {})

    def test_recreation_backs_up_exact_readonly_healthcheck_bind_before_allowing(self):
        with tempfile.TemporaryDirectory() as temporary:
            backup=Path(temporary)
            item={'Id':'abc','State':{'StartedAt':'2026-10-20T10:00:00Z'},
                  'Mounts':[{'Type':'bind','Source':str(ROOT/'healthcheck.py'),
                             'Destination':'/healthcheck.py','RW':False}]}
            result=subprocess.CompletedProcess(['podman','diff'],0,'C /etc\nA /healthcheck.py\n','')
            with patch.object(azraelctl,'run',return_value=result), \
                 patch.object(azraelctl,'make_backup_directory',return_value=backup):
                audit=azraelctl.audit_recreation('external-tools',item,{})
            self.assertEqual(audit['status'],'clean')
            saved=backup/'important-files/external-tools/healthcheck.py'
            self.assertEqual(saved.read_bytes(),(ROOT/'healthcheck.py').read_bytes())
            manifest=json.loads((backup/'readonly-bind-manifest.json').read_text())
            self.assertTrue(manifest['read_only'])
            self.assertEqual(manifest['verification'],'passed')

    def test_recreation_does_not_exempt_writable_healthcheck_mount(self):
        item={'Id':'abc','State':{'StartedAt':'2026-10-20T10:00:00Z'},
              'Mounts':[{'Type':'bind','Source':str(ROOT/'healthcheck.py'),
                         'Destination':'/healthcheck.py','RW':True}]}
        result=subprocess.CompletedProcess(['podman','diff'],0,'A /healthcheck.py\n','')
        with patch.object(azraelctl,'run',return_value=result):
            with self.assertRaisesRegex(azraelctl.DeploymentError,'expected read-only project bind'):
                azraelctl.audit_recreation('external-tools',item,{})

    def test_mountpoint_only_layer_changes_are_verified_against_persistent_bind_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            storage = root / 'storage'; storage.mkdir()
            bind_file = ROOT / 'healthcheck.py'
            item = {'Id': 'dashboard-id', 'State': {'StartedAt': '2026-10-20T10:00:00Z'},
                    'Mounts': [
                        {'Type': 'bind', 'Source': str(bind_file), 'Destination': '/app/data-legacy', 'RW': False},
                        {'Type': 'bind', 'Source': str(bind_file), 'Destination': '/app/artifacts-legacy', 'RW': False},
                        {'Type': 'bind', 'Source': str(storage), 'Destination': '/var/lib/azrael54', 'RW': True}]}
            diff = ('C /app\nA /app/data-legacy\nA /app/artifacts-legacy\n'
                    'C /var\nC /var/lib\nA /var/lib/azrael54\n')
            with patch.object(azraelctl, 'BACKUP_ROOT', root / 'backups'), \
                    patch.dict(os.environ, {'AZRAEL_STORAGE_ROOT': str(storage)}):
                result = azraelctl.verify_bind_mountpoint_diff('dashboard', item, diff.splitlines())
            self.assertEqual(len(result), 3)
            manifest = json.loads(Path(result[0]['backup']).read_text())
            self.assertEqual(manifest['status'], 'verified_mountpoints_only')
            self.assertEqual(len(manifest['diff_entries']), 6)

    def test_bind_mount_audit_never_exempts_files_inside_a_mount(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); storage = root / 'storage'; storage.mkdir()
            item = {'Mounts': [{'Type': 'bind', 'Source': str(storage),
                                'Destination': '/var/lib/azrael54', 'RW': True}]}
            with patch.dict(os.environ, {'AZRAEL_STORAGE_ROOT': str(storage)}):
                result = azraelctl.verify_bind_mountpoint_diff(
                    'dashboard', item, ['A /var/lib/azrael54/database.sqlite'])
            self.assertEqual(result, [])

    def test_start_uses_no_recreate_and_scoped_compose_commands(self):
        with patch.object(azraelctl, 'run') as run, patch.object(azraelctl,'provider_env',return_value={'PODMAN_COMPOSE_PROVIDER':'fixture-provider'}):
            azraelctl.run_compose_up('dashboard', gpu=False, force=False, env={})
        command = run.call_args.args[0]
        self.assertIn('--no-deps', command)
        self.assertIn('--no-recreate', command)
        self.assertNotIn('--force-recreate', command)
        self.assertEqual(command[-1], 'dashboard')

    def test_compose_signature_is_stable_for_unchanged_configuration(self):
        self.assertEqual(azraelctl.compose_signature(), azraelctl.compose_signature())
        self.assertEqual(azraelctl.compose_service_signatures(), azraelctl.compose_service_signatures())

    def test_service_config_change_does_not_recreate_unrelated_healthy_containers(self):
        item = {'State': {'Status': 'running', 'Health': {'Status': 'healthy'}},
                'HostConfig': {'RestartPolicy': {'Name': 'unless-stopped'}}, 'Image': 'sha256:image'}
        old_state = {'compose_signature': 'older-project-wide-signature'}
        self.assertFalse(azraelctl.needs_recreation('tools', item, 'sha256:image', 'new-project-signature',
                                                    old_state, gpu=False, service_signature='tools-config'))
        old_state['service_signatures'] = {'tools': 'prior-tools-config'}
        self.assertTrue(azraelctl.needs_recreation('tools', item, 'sha256:image', 'new-project-signature',
                                                   old_state, gpu=False, service_signature='tools-config'))

    def test_healthy_juice_shop_with_verified_persistent_mounts_ignores_rotating_snapshot_tag(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            storage = root / 'storage'; storage.mkdir()
            bind_map = {
                '/juice-shop/data': 'data', '/juice-shop/logs': 'logs',
                '/juice-shop/ftp': 'ftp', '/juice-shop/.well-known/csaf': 'csaf',
                '/juice-shop/frontend/dist/frontend': 'frontend', '/juice-shop/i18n': 'i18n',
            }
            mounts = []
            variables = {'AZRAEL_STORAGE_ROOT': str(storage), 'AZRAEL_WEB_LAB_SHELL': str(root / 'busybox')}
            for destination, name in bind_map.items():
                source = storage / ('juice-shop-' + name); source.mkdir()
                variable = 'AZRAEL_JUICE_SHOP_' + name.upper() + '_ROOT'
                variables[variable] = str(source)
                mounts.append({'Type': 'bind', 'Source': str(source), 'Destination': destination, 'RW': True})
            health = root / 'healthcheck.js'; health.write_text('')
            busybox = root / 'busybox'; busybox.write_text('')
            mounts.extend([
                {'Type': 'bind', 'Source': str(health), 'Destination': '/healthcheck.js', 'RW': False},
                {'Type': 'bind', 'Source': str(busybox), 'Destination': '/bin/sh', 'RW': False},
            ])
            with patch.dict(os.environ, variables, clear=True), patch.object(azraelctl, 'ROOT', root):
                item = {'State': {'Status': 'running', 'Health': {'Status': 'healthy'}},
                        'HostConfig': {'RestartPolicy': {'Name': 'unless-stopped'}},
                        'Image': 'sha256:old-snapshot', 'Mounts': mounts}
                self.assertTrue(azraelctl.web_lab_persistent_mounts_ready(item))
                self.assertFalse(azraelctl.needs_recreation('web-lab', item, 'sha256:rotated-snapshot',
                                                           'signature', {}, gpu=False))
                item['Mounts'] = mounts[:-2] + [dict(mounts[-2], RW=True), mounts[-1]]
                self.assertFalse(azraelctl.web_lab_persistent_mounts_ready(item))

    def test_podman_compose_patch_keeps_partial_recreates_service_scoped(self):
        source = '''def get_excluded(compose, args):
    excluded = set()
    if args.services:
        excluded = set(compose.services)
        for service in args.services:
            excluded -= compose.services[service]["_deps"]
            excluded.discard(service)
    log("** excluding: ", excluded)
    return excluded

    if args.force_recreate or len(diff_hashes):
        log("recreating: ...")
        down_args = argparse.Namespace(**dict(args.__dict__, volumes=False))
        compose.commands["down"](compose, down_args)
        log("recreating: done\\n\\n")
'''
        patched = azraelctl.patch_podman_compose_source(source)
        self.assertIn('getattr(args, "no_deps", False)', patched)
        self.assertIn('recreating selected services only', patched)
        self.assertIn('compose.podman.run([], "rm", ["--force", cnt["name"]])', patched)
        self.assertIn('elif args.force_recreate or len(diff_hashes)', patched)

    def test_persistent_user_unit_uses_service_recovery_and_no_competing_restart_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            commands = []

            def fake_run(command, **kwargs):
                commands.append(command)
                output = 'active\n' if command[-2:] == ['is-active', 'azrael54.service'] else ''
                return subprocess.CompletedProcess(command, 0, output, '')

            with patch.object(azraelctl, 'SYSTEMD_DIR', root), \
                    patch.object(azraelctl, 'UNIT_FILE', root / 'azrael54.service'), \
                    patch.object(azraelctl, 'provider_executable', return_value='/tmp/provider'), \
                    patch.object(azraelctl, 'compose_prefix', return_value=['/usr/bin/podman', 'compose']), \
                    patch.object(azraelctl.shutil, 'which', return_value=None), \
                    patch.object(azraelctl, 'run', side_effect=fake_run):
                result = azraelctl.boot_service_manager('cpu', 8765)
            unit = (root / 'azrael54.service').read_text()
            self.assertTrue(result['unit_active'])
            self.assertIn('ExecStart=' + str(ROOT / 'azraelctl') + ' _service-start', unit)
            self.assertIn('ExecStop=' + str(ROOT / 'azraelctl') + ' _service-stop', unit)
            self.assertNotIn('Restart=', unit)
            self.assertIn(['systemctl', '--user', 'enable', '--now', 'azrael54.service'], commands)

    def test_gpu_worker_failure_retries_once_on_cpu(self):
        import slm

        class Bus:
            def snapshot(self): return []
            def send(self, *args, **kwargs): pass

        class App:
            lock = threading.RLock()
            jobs = []
            team = type('Team', (), {'bus': Bus()})()
            evidence = type('Evidence', (), {'list_records': lambda self, count: []})()
            role_research = type('Research', (), {'context': lambda self, role: {}})()
            workspace = type('Workspace', (), {'search_references': lambda self, query: {
                'documentation': [], 'repository_metadata': []}})()
            directives = type('Directives', (), {'snapshot': lambda self: {'assignments': {
                'analyst': {'profile': 'default', 'objective': 'review'}},
                'problem_solving_directive': 'Think outside the box; explore loopholes only in authorized scope.'}})()

        results = [subprocess.CompletedProcess([], 1, '', 'CUDA out of memory'),
                   subprocess.CompletedProcess([], 0, '{"text":"CPU recovery"}', '')]
        with patch.object(slm, 'available', return_value=True), \
             patch.object(slm.subprocess, 'run', side_effect=results) as worker:
            response = slm.ask(App(), 'admin_chat', 'status?', device_selector='GPU-test')
        self.assertEqual(response['text'], 'CPU recovery')
        self.assertIn('retried once on CPU', response['gpu_fallback_reason'])
        self.assertEqual(worker.call_count, 2)
        self.assertEqual(worker.call_args.kwargs['env']['AZRAEL_GPU_ENABLED'], 'false')
        payload=json.loads(worker.call_args.kwargs['input'])
        self.assertIn('loopholes only in authorized scope',payload['context']['admin_directive']['problem_solving'])
        self.assertIn('never overrides target allowlists',payload['context']['admin_directive']['authority'])

    def test_status_reports_unavailable_health_endpoint_without_crashing(self):
        import setup_lab
        output = __import__('io').StringIO()
        with patch.object(azraelctl, 'provider_env', return_value={}), \
             patch.object(azraelctl, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')), \
             patch.object(setup_lab, '_http', side_effect=OSError('connection refused')), \
             patch.object(setup_lab, 'gpu_status', return_value={'host_gpu_detected': False}), \
             patch.object(azraelctl, 'STATE', Path('/nonexistent/azrael54-test-state')):
            with __import__('contextlib').redirect_stdout(output):
                azraelctl.operational_status()
        self.assertIn('healthz: unavailable', output.getvalue())

    def test_cpu_verify_reports_no_cuda_training_step_without_unbound_fields(self):
        import setup_lab
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / 'deployment-state.json'
            state.write_text(json.dumps({'profile': 'cpu'}))
            with patch.dict(os.environ), \
                    patch.object(azraelctl, 'RUNTIME', root), \
                    patch.object(azraelctl, 'STATE', state), \
                    patch.object(azraelctl, 'read_compose_env', return_value={
                        'AZRAEL_PORT': '8765', 'AZRAEL_STORAGE_ROOT': str(root / 'storage')}), \
                    patch.object(azraelctl, 'provider_env', return_value={}), \
                    patch.object(azraelctl, 'current_containers', return_value={name: {} for name in azraelctl.SERVICES}), \
                    patch.object(setup_lab, 'wait_for_services_healthy'), \
                    patch.object(azraelctl, 'verify_http_surface', return_value={'frontend': 'passed'}), \
                    patch.object(setup_lab, 'verify_dashboard', return_value={'api_login': 'passed'}), \
                    patch.object(setup_lab, 'verify_internal_services', return_value={'status': 'passed'}), \
                    patch.object(setup_lab, 'verify_slm', return_value={'status': 'passed', 'device': 'cpu'}):
                result = azraelctl.verify_deployment()
            self.assertEqual(result['training_step'], {'multi_gpu': None, 'individual_devices': []})


if __name__ == '__main__':
    unittest.main()
