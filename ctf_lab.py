"""Locally staged, provenance-preserving offline CTF practice challenges."""
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3

import storage_paths

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / 'ctf_assets'
CHALLENGE_ID = re.compile(r'ctf-[0-9]{2}-[a-z0-9-]{1,80}\Z')
SOURCE_REPOSITORY = 'https://github.com/zachflower/ctfd-challenge-assets'
SOURCE_COMMIT = 'bb8ce4ed14f02eea85e84273e537b865c707e332'


class CtfIntegrityError(RuntimeError):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def _utc():
    return datetime.now(timezone.utc).isoformat()


class CtfLab:
    """Read-only challenge catalog plus a separate, answer-free attempt ledger."""

    def __init__(self, root=None):
        self.root = Path(root) if root else storage_paths.training_root(ROOT, 'ctf')
        self.available = False
        self.error = None
        self._catalog = None
        self._answers = None
        try:
            self._initialize()
            self.available = True
        except (OSError, ValueError, KeyError, TypeError, CtfIntegrityError) as error:
            self.error = str(error)[:300]

    def _read_template(self):
        catalog = json.loads((ASSETS / 'catalog.json').read_text())
        answer_key = json.loads((ASSETS / 'organizer-answer-key.json').read_text())
        if catalog.get('schema') != 'azrael-ctf-catalog/1' or answer_key.get('schema') != 'azrael-ctf-answer-key/1':
            raise CtfIntegrityError('CTF source assets have unsupported schemas')
        source = catalog.get('source', {})
        if source.get('source_repository') != SOURCE_REPOSITORY or source.get('source_commit') != SOURCE_COMMIT:
            raise CtfIntegrityError('CTF source commit does not match the pinned public repository revision')
        source_csv = ASSETS / 'source' / 'dailies.csv'
        if source_csv.is_file() and _sha(source_csv.read_bytes()) != source.get('source_sha256'):
            raise CtfIntegrityError('Preserved CTF source CSV hash failed verification')
        if answer_key.get('source_sha256') != source.get('source_sha256'):
            raise CtfIntegrityError('CTF answer-key provenance hash failed verification')
        if not (ASSETS / 'source' / 'LICENSE.md').is_file():
            raise CtfIntegrityError('MIT license text is missing from the CTF source bundle')
        source_metadata = json.loads((ASSETS / 'source' / 'SOURCE.json').read_text())
        if source_metadata != source:
            raise CtfIntegrityError('CTF source metadata differs from the catalog provenance')
        challenges = catalog.get('challenges')
        answers = answer_key.get('answers')
        if not isinstance(challenges, list) or not 1 <= len(challenges) <= 100:
            raise CtfIntegrityError('CTF catalog challenge count is outside the supported bound')
        expected_ids = set()
        for item in challenges:
            if not isinstance(item, dict) or not CHALLENGE_ID.fullmatch(item.get('id', '')):
                raise CtfIntegrityError('CTF challenge has an invalid identifier')
            if item['id'] in expected_ids:
                raise CtfIntegrityError('CTF challenge identifiers must be unique')
            expected_ids.add(item['id'])
            if (not isinstance(item.get('description'), str) or not 1 <= len(item['description']) <= 2000 or
                    re.search(r'https?://', item['description'], re.I)):
                raise CtfIntegrityError('Only bounded, self-contained offline CTF prompts are supported')
        if not isinstance(answers, dict) or set(answers) != expected_ids:
            raise CtfIntegrityError('CTF answer key does not exactly match the challenge catalog')
        if any(not isinstance(value, str) or not 1 <= len(value) <= 160 for value in answers.values()):
            raise CtfIntegrityError('CTF answer key contains an invalid flag value')
        return catalog, answer_key

    def _initialize(self):
        if self.root.exists() and self.root.is_symlink():
            raise CtfIntegrityError('CTF storage root cannot be a symlink')
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.stat().st_uid != os.getuid():
            raise CtfIntegrityError('CTF storage must be owned by the AZRAEL service user')
        self.root.chmod(0o700)
        catalog_path = self.root / 'catalog.json'
        answer_path = self.root / 'organizer-answer-key.json'
        source_path = self.root / 'source.json'
        license_path = self.root / 'LICENSE.md'
        manifest_path = self.root / 'integrity.json'
        paths = (catalog_path, answer_path, source_path, license_path, manifest_path)
        existing = [path.exists() for path in paths]
        if any(existing) and not all(existing):
            raise CtfIntegrityError('Existing CTF store is incomplete; refusing to overwrite or recreate it')
        if not any(existing):
            catalog, answer_key = self._read_template()
            catalog_bytes = (_canonical(catalog) + '\n').encode()
            answer_bytes = (_canonical(answer_key) + '\n').encode()
            source_bytes = (_canonical(catalog['source']) + '\n').encode()
            license_bytes = (ASSETS / 'source' / 'LICENSE.md').read_bytes()
            integrity = {'schema': 'azrael-ctf-integrity/1', 'source_commit': SOURCE_COMMIT,
                         'source_sha256': catalog['source']['source_sha256'],
                         'catalog_sha256': _sha(catalog_bytes), 'answer_key_sha256': _sha(answer_bytes),
                         'license_sha256': _sha(license_bytes), 'created_at': _utc()}
            self._create_private(catalog_path, catalog_bytes)
            self._create_private(answer_path, answer_bytes)
            self._create_private(source_path, source_bytes)
            self._create_private(license_path, license_bytes)
            self._create_private(manifest_path, (_canonical(integrity) + '\n').encode())
            self._initialize_attempts()
        else:
            catalog = json.loads(catalog_path.read_text())
            answer_key = json.loads(answer_path.read_text())
            integrity = json.loads(manifest_path.read_text())
            if (integrity.get('schema') != 'azrael-ctf-integrity/1' or
                    _sha(catalog_path.read_bytes()) != integrity.get('catalog_sha256') or
                    _sha(answer_path.read_bytes()) != integrity.get('answer_key_sha256') or
                    _sha(license_path.read_bytes()) != integrity.get('license_sha256') or
                    integrity.get('source_commit') != SOURCE_COMMIT):
                raise CtfIntegrityError('Persisted CTF store failed integrity verification')
            self._initialize_attempts()
        self._catalog, self._answers = catalog, answer_key['answers']

    @staticmethod
    def _create_private(path, content):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

    def _initialize_attempts(self):
        path = self.root / 'progress.sqlite3'
        if path.is_symlink():
            raise CtfIntegrityError('CTF progress database cannot be a symlink')
        with sqlite3.connect(path, timeout=5) as connection:
            connection.execute('PRAGMA busy_timeout=5000')
            connection.execute('''CREATE TABLE IF NOT EXISTS attempts(
              id INTEGER PRIMARY KEY AUTOINCREMENT, challenge_id TEXT NOT NULL,
              method TEXT NOT NULL, role TEXT, submitted_sha256 TEXT NOT NULL,
              correct INTEGER NOT NULL, created_at TEXT NOT NULL)''')
        path.chmod(0o600)

    def status(self):
        if not self.available:
            return {'status': 'unavailable', 'error': self.error,
                    'training_data': False, 'operational_evidence': False}
        with sqlite3.connect(self.root / 'progress.sqlite3', timeout=5) as connection:
            total, solved = connection.execute('''SELECT count(*), count(DISTINCT CASE WHEN correct=1
              THEN challenge_id END) FROM attempts''').fetchone()
        source = self._catalog['source']
        return {'status': 'ready', 'challenge_count': len(self._catalog['challenges']),
                'attempt_count': total, 'solved_count': solved, 'source_repository': source['source_repository'],
                'source_commit': source['source_commit'], 'license': source['license'],
                'network_targets': 0, 'executable_assets': 0,
                'training_data': False, 'operational_evidence': False,
                'note': 'Public CTF practice only; attempts are isolated from evidence and training datasets.'}

    def catalog(self):
        if not self.available:
            raise RuntimeError(self.error or 'Offline CTF catalog is unavailable')
        with sqlite3.connect(self.root / 'progress.sqlite3', timeout=5) as connection:
            stats = {row[0]: {'attempts': row[1], 'solved': bool(row[2])} for row in connection.execute(
                '''SELECT challenge_id, count(*), max(correct) FROM attempts GROUP BY challenge_id''')}
        result = []
        for item in self._catalog['challenges']:
            row = {key: value for key, value in item.items() if key not in {'source_commit'}}
            row['source'] = {'repository': SOURCE_REPOSITORY, 'commit': SOURCE_COMMIT,
                             'license': self._catalog['source']['license']}
            row.update(stats.get(item['id'], {'attempts': 0, 'solved': False}))
            result.append(row)
        return {'status': 'ready', 'source': self._catalog['source'], 'challenges': result,
                'answers_disclosed': False, 'network_targets': 0, 'executable_assets': 0}

    def challenge(self, challenge_id):
        if not self.available:
            raise RuntimeError(self.error or 'Offline CTF catalog is unavailable')
        if not isinstance(challenge_id, str) or not CHALLENGE_ID.fullmatch(challenge_id):
            raise ValueError('Invalid CTF challenge identifier')
        item = next((value for value in self._catalog['challenges'] if value['id'] == challenge_id), None)
        if item is None:
            raise ValueError('Unknown CTF challenge')
        return item

    def practice_prompt(self, challenge_id):
        item = self.challenge(challenge_id)
        prompt = ('Solve this published, offline CTF exercise using the supplied text only. '
                  'Do not contact external systems or execute commands. Explain the decoding steps briefly, '
                  'then give the exact flag if you can determine it.\n' +
                  _canonical({'title': item['title'], 'category': item['category'],
                              'description': item['description'], 'hint': item['hint']}))
        if len(prompt) > 3000:
            raise ValueError('CTF practice prompt exceeds its input bound')
        return prompt

    def attempt(self, challenge_id, submitted, method='operator', role=None):
        self.challenge(challenge_id)
        if not isinstance(submitted, str) or not 1 <= len(submitted) <= 4096:
            raise ValueError('CTF submission must contain 1 through 4096 characters')
        if method not in {'operator', 'model'}:
            raise ValueError('Invalid CTF attempt method')
        if role is not None and (not isinstance(role, str) or not re.fullmatch(r'[a-z][a-z0-9_]{1,40}', role)):
            raise ValueError('Invalid CTF role label')
        answer = self._answers[challenge_id]
        correct = hmac.compare_digest(submitted.strip(), answer) if method == 'operator' else answer in submitted
        with sqlite3.connect(self.root / 'progress.sqlite3', timeout=5) as connection:
            connection.execute('PRAGMA busy_timeout=5000')
            connection.execute('''INSERT INTO attempts(challenge_id,method,role,submitted_sha256,correct,created_at)
                VALUES(?,?,?,?,?,?)''', (challenge_id, method, role, _sha(submitted), int(correct), _utc()))
        return {'challenge_id': challenge_id, 'correct': bool(correct), 'solved': bool(correct),
                'method': method, 'answer_returned': False}
