"""Live-mission coordinator contracts; fixtures contain no claimed host telemetry."""
import tempfile
import threading
import time
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import ops_api
from evidence_store import EvidenceStore
from training_coordinator import TASK_PLAN, TrainingCoordinator


class FakeApp:
    def __init__(self, root):
        self.lock = threading.RLock()
        self.busy = False
        self.evidence = EvidenceStore(Path(root) / 'evidence')


def observed_snapshot():
    return {
        'system': {'status': 'healthy', 'cpu_cores_available_to_process': 4,
                   'container_memory': {'memory_current_bytes': 10, 'memory_limit_bytes': 100},
                   'storage': {'exists': True, 'capacity_status': 'ok'}},
        'services': {'status': 'passed', 'services': [
            {'service': 'dashboard', 'status': 'healthy', 'http_status': 200, 'method': 'local check'}],
            'web_lab_network_policy': 'internal lab network; no host port published'},
        'gpus': {'status': 'unavailable', 'driver_version': None, 'cuda_runtime': None, 'devices': []},
        'models': {'status': 'ready', 'models': [{'id': 'local-model', 'available': True}]},
        'datasets': {'summary': {'records': 0}, 'datasets': []},
        'evidence': {'records': 0},
        'source': {'kind': 'test fixture for coordinator contract', 'synthetic': False,
                   'external_targets_contacted': False, 'endpoint_control': False},
    }


class TrainingCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.app = FakeApp(self.temporary.name)
        self.coordinator = TrainingCoordinator(self.app)
        self.addCleanup(self.coordinator.close)
        self.addCleanup(self.temporary.cleanup)

    def patch_observations(self):
        return [
            patch.object(ops_api, 'system_status', return_value=observed_snapshot()['system']),
            patch.object(ops_api, 'container_health', return_value=observed_snapshot()['services']),
            patch.object(ops_api, 'gpu_inventory', return_value=observed_snapshot()['gpus']),
            patch.object(ops_api, 'model_inventory', return_value=observed_snapshot()['models']),
            patch.object(ops_api, 'dataset_status', return_value=observed_snapshot()['datasets']),
            patch.object(ops_api, 'evidence_status', return_value={'summary': observed_snapshot()['evidence']}),
        ]

    @staticmethod
    def wait_for(coordinator, mission_id, states=('pending_review', 'partial', 'cancelled'), timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            mission = coordinator.get(mission_id)
            if mission['status'] in states:
                return mission
            time.sleep(.01)
        raise AssertionError('mission did not reach a terminal review state')

    def test_operator_approved_live_mission_uses_serial_role_dispatch_and_human_review(self):
        calls = []

        def ask(app, mode, prompt, role, cancel_event=None):
            calls.append(role)
            self.assertFalse(cancel_event.is_set())
            return {'text': f'{role}: observations reviewed; no active incident established.',
                    'model': 'local-test-model', 'device_name': 'CPU'}

        patches = self.patch_observations()
        for item in patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(patches)])
        with patch('slm.ask', side_effect=ask):
            with self.assertRaisesRegex(ValueError, 'approval'):
                self.coordinator.start({'approved': False})
            response = self.coordinator.start({'approved': True, 'priority': 'normal'})
            mission = self.wait_for(self.coordinator, response['mission_id'])
        self.assertEqual(mission['status'], 'pending_review')
        self.assertEqual(calls, [role for _, role, _, _ in TASK_PLAN])
        self.assertEqual(len(mission['tasks']), len(TASK_PLAN))
        self.assertTrue(all(task['state'] == 'completed' for task in mission['tasks']))
        self.assertEqual(mission['snapshot']['source']['synthetic'], False)
        self.assertEqual(mission['completion_score'], 100.0)
        self.assertTrue(all(task['output']['verified'] is False for task in mission['tasks']))
        with self.assertRaisesRegex(ValueError, 'human-reviewed'):
            self.coordinator.export(mission['id'])
        reviewed = self.coordinator.review(mission['id'], {
            'decision': 'accept', 'note': 'Snapshot and every role output reviewed.',
            'confidence': .91, 'split': 'test'})
        exported = self.coordinator.export(mission['id'])
        self.assertEqual(reviewed['review_status'], 'accepted')
        self.assertEqual(exported['dataset_split'], 'test')
        self.assertFalse(exported['training_eligible'])
        self.assertFalse(exported['model_training_performed'])
        self.assertTrue(reviewed['dataset_version_hash'])

    def test_large_live_observation_is_compacted_below_shared_slm_limit(self):
        from training_coordinator import sha
        snapshot = observed_snapshot()
        snapshot['system']['storage'].update({f'detail_{i}': 'x' * 100 for i in range(30)})
        snapshot['topology'] = {
            'source_sha256': 'a' * 64,
            'nodes': [{'id': f'service-{i}', 'networks': ['internal'],
                       'host_published': False, 'host_bindings': []} for i in range(40)],
            'networks': [{'id': 'internal', 'internal': True}],
            'edges': [{'service': f'service-{i}', 'network': 'internal'} for i in range(40)],
        }
        mission = {'source_sha256': sha('measured snapshot'), 'snapshot': snapshot}
        task = {'task_key': 'evaluation', 'role': 'defender'}
        prior = [{'phase': 'review', 'role': f'role-{i}', 'text': 'x' * 32768,
                  'output_sha256': sha(str(i))} for i in range(4)]
        prompt = self.coordinator._task_prompt(mission, task, prior)
        self.assertLessEqual(len(prompt), 4096)
        self.assertIn(sha('measured snapshot'), prompt)
        self.assertIn('service-0', prompt)

    def test_unhandled_coordinator_error_is_saved_as_partial_not_left_running(self):
        patches = self.patch_observations()
        for item in patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(patches)])
        with patch.object(self.coordinator, '_task_prompt', side_effect=ValueError('input too large')):
            response = self.coordinator.start({'approved': True})
            mission = self.wait_for(self.coordinator, response['mission_id'])
        self.assertEqual(mission['status'], 'partial')
        self.assertEqual(mission['error'], 'ValueError')
        self.assertTrue(all(task['state'] == 'interrupted' for task in mission['tasks']))
        self.assertIn('mission_interrupted_by_coordinator_error', [event['event'] for event in mission['audit']])

    def test_emergency_stop_cancels_active_local_inference_only(self):
        started = threading.Event()

        def ask(app, mode, prompt, role, cancel_event=None):
            started.set()
            cancel_event.wait(3)
            raise RuntimeError('cancelled')

        patches = self.patch_observations()
        for item in patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(patches)])
        with patch('slm.ask', side_effect=ask):
            response = self.coordinator.start({'approved': True})
            self.assertTrue(started.wait(1))
            result = self.coordinator.emergency_stop()
            mission = self.wait_for(self.coordinator, response['mission_id'])
        self.assertEqual(result['effect'].split(';')[1].strip(), 'AZRAEL services are unaffected.')
        self.assertTrue(self.coordinator.status()['emergency_stopped'])
        self.assertEqual(mission['status'], 'cancelled')
        self.assertFalse(self.app.busy)

    def test_review_rejects_invalid_confidence_and_cross_split_duplicate_measurement(self):
        first, second = 'a' * 32, 'b' * 32
        with self.app.evidence.connect() as con:
            for mission_id in (first, second):
                con.execute('''INSERT INTO training_missions
                    (id,scenario_id,scenario_version,status,priority,source_sha256,snapshot,created_at,finished_at,completion_score,review_status)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                    (mission_id, 'live', '1', 'pending_review', 3, 'same-source', '{}',
                     '2026-10-20T00:00:00+00:00', '2026-10-20T00:01:00+00:00', 100, 'pending_review'))
        with self.assertRaisesRegex(ValueError, 'confidence'):
            self.coordinator.review(first, {'decision': 'accept', 'note': 'Reviewed record',
                                            'confidence': 2, 'split': 'training'})
        self.coordinator.review(first, {'decision': 'accept', 'note': 'Reviewed record',
                                        'confidence': .8, 'split': 'training'})
        with self.assertRaisesRegex(ValueError, 'cannot cross dataset splits'):
            self.coordinator.review(second, {'decision': 'accept', 'note': 'Reviewed record',
                                             'confidence': .8, 'split': 'validation'})

    def test_cancellable_shared_slm_runner_terminates_its_child_process(self):
        import slm
        event = threading.Event()
        timer = threading.Timer(.1, event.set)
        timer.start()
        self.addCleanup(timer.cancel)
        with self.assertRaises(slm.InferenceCancelled):
            slm._run_worker([os.sys.executable, '-c', 'import time; time.sleep(15)'],
                            '', os.environ.copy(), event)


if __name__ == '__main__':
    unittest.main()
