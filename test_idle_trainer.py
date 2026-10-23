import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from evidence_store import EvidenceStore
from idle_trainer import IdleTrainer


class FakeTeam:
    class Bus:
        pass
    bus = Bus()


class FakeTrainer:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = []

    def _datasets(self, datasets):
        if set(datasets) != {'train', 'validation', 'test'}:
            raise ValueError('three splits required')
        return {'validated': True}

    def train(self, request, bus):
        self.calls.append(request)
        self.started.set()
        self.release.wait(3)
        return {'run_id': 'a' * 32, 'compute_device': 'cpu', 'training_occurred': True}


class FakeApp:
    def __init__(self, root):
        self.lock = threading.RLock()
        self.busy = False
        self.team = FakeTeam()
        self.evidence = EvidenceStore(Path(root) / 'evidence')


class IdleTrainerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = FakeApp(self.temp.name)
        self.trainer = FakeTrainer()
        self.idle = IdleTrainer(self.app, self.trainer)
        self.addCleanup(self.idle.close)
        self.request = {'confirmed': True, 'datasets': {
            'train': 'a' * 64, 'validation': 'b' * 64, 'test': 'c' * 64}}

    def wait_for(self, job_id, status, timeout=3):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            job = next(item for item in self.idle.list() if item['id'] == job_id)
            if job['status'] == status:
                return job
            time.sleep(.01)
        self.fail(f'idle training job did not reach {status}')

    def test_job_waits_for_shared_work_to_be_idle_then_runs_and_records_result(self):
        self.app.busy = True
        queued = self.idle.enqueue(self.request)
        self.assertEqual(queued['status'], 'queued')
        time.sleep(.1)
        self.assertFalse(self.trainer.started.is_set())
        self.assertEqual(self.idle.status()['status'], 'waiting_for_idle')
        self.app.busy = False
        self.idle._wake.set()
        self.assertTrue(self.trainer.started.wait(1))
        self.assertTrue(self.app.busy)
        self.trainer.release.set()
        job = self.wait_for(queued['job_id'], 'completed')
        self.assertTrue(job['result']['training_occurred'])
        self.assertFalse(self.app.busy)

    def test_requires_explicit_operator_confirmation(self):
        with self.assertRaisesRegex(ValueError, 'confirmation'):
            self.idle.enqueue({**self.request, 'confirmed': False})
        self.assertEqual(self.trainer.calls, [])

    def test_previous_queued_jobs_are_interrupted_instead_of_resumed(self):
        with self.app.evidence.connect() as connection:
            connection.execute('''INSERT INTO idle_training_jobs
                (id,status,request,requested_by,requested_at) VALUES(?,?,?,?,?)''',
                ('d' * 32, 'queued', json.dumps(self.request), 'authenticated_admin', '2026-01-01T00:00:00Z'))
        other = IdleTrainer(self.app, self.trainer)
        try:
            row = next(item for item in other.list() if item['id'] == 'd' * 32)
            self.assertEqual(row['status'], 'interrupted')
            self.assertEqual(self.trainer.calls, [])
        finally:
            other.close()


if __name__ == '__main__':
    unittest.main()
