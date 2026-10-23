import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ctf_lab import CtfLab


class CtfLabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.lab = CtfLab(Path(self.temp.name) / 'ctf')
        self.addCleanup(self.temp.cleanup)

    def test_pinned_offline_catalog_hides_answers_and_keeps_progress_separate(self):
        self.assertTrue(self.lab.available, self.lab.error)
        result = self.lab.catalog()
        self.assertEqual(len(result['challenges']), 20)
        self.assertFalse(result['answers_disclosed'])
        self.assertEqual(result['network_targets'], 0)
        self.assertTrue(all('answer' not in item and 'flag' not in item for item in result['challenges']))
        challenge = result['challenges'][0]
        expected = json.loads((Path(self.temp.name) / 'ctf' / 'organizer-answer-key.json').read_text())['answers'][challenge['id']]
        prompt = self.lab.practice_prompt(challenge['id'])
        self.assertNotIn(expected, prompt)
        wrong = self.lab.attempt(challenge['id'], 'flag{wrong}')
        right = self.lab.attempt(challenge['id'], expected)
        self.assertFalse(wrong['correct'])
        self.assertTrue(right['correct'])
        database = (Path(self.temp.name) / 'ctf' / 'progress.sqlite3').read_bytes()
        self.assertNotIn(expected.encode(), database)
        key = Path(self.temp.name) / 'ctf' / 'organizer-answer-key.json'
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)
        self.assertTrue(self.lab.status()['operational_evidence'] is False)

    def test_invalid_existing_ctf_store_is_preserved_and_not_reseeded(self):
        path = Path(self.temp.name) / 'ctf' / 'organizer-answer-key.json'
        original = path.read_bytes()
        path.write_bytes(original + b' ')
        damaged = path.read_bytes()
        reopened = CtfLab(Path(self.temp.name) / 'ctf')
        self.assertFalse(reopened.available)
        self.assertIn('integrity', reopened.error.lower())
        self.assertEqual(path.read_bytes(), damaged)

    def test_attempt_validation_and_unknown_challenge_fail_closed(self):
        with self.assertRaises(ValueError):
            self.lab.attempt('../escape', 'flag{bad}')
        with self.assertRaises(ValueError):
            self.lab.attempt(self.lab.catalog()['challenges'][0]['id'], '')


if __name__ == '__main__':
    unittest.main()
