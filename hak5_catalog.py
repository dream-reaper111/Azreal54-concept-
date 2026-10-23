"""Explicit official repository metadata collection; no code or payload downloads."""
import hashlib
import json
import os
from pathlib import Path
import re
from evidence_store import EvidenceStore, packed, utc

URL = 'https://api.github.com/orgs/hak5/repos?type=public&per_page=100&page={}'
DEFAULT_ROOT = Path(__file__).parent / 'artifacts'


def sanitize(value):
    name = value.get('name')
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', name):
        raise ValueError('Invalid repository name')
    full = 'hak5/' + name
    canonical = 'https://github.com/' + full
    if value.get('owner', {}).get('login', '').lower() != 'hak5' or value.get('full_name') != full or value.get('html_url') != canonical:
        raise ValueError('Repository identity does not match official organization')
    result = {'full_name': full, 'html_url': canonical}
    for key, bound in [('description', 500), ('default_branch', 100), ('created_at', 50), ('updated_at', 50), ('pushed_at', 50)]:
        text = value.get(key)
        if text is not None and not isinstance(text, str):
            raise ValueError('Invalid repository metadata')
        result[key] = text[:bound] if text is not None else None
    for key in ('fork', 'archived'):
        if type(value.get(key)) is not bool:
            raise ValueError('Invalid repository boolean')
        result[key] = value[key]
    license_value = value.get('license')
    result['declared_spdx'] = license_value.get('spdx_id', '')[:100] if isinstance(license_value, dict) and isinstance(license_value.get('spdx_id'), str) else None
    return result


def refresh(store_root, fetch=None):
    if fetch is None:
        from source_transport import fetch
    store = EvidenceStore(store_root)
    collected = utc()
    report = {'retrieved_at': collected, 'pages': [], 'items': 0, 'accepted': 0, 'quarantined': 0, 'rejected': 0, 'truncated': False, 'training_occurred': False, 'visibility': 'all_registered_roles', 'task_routes': [], 'limitations': ['Repository metadata supports reference retrieval only.', 'API license declarations are unverified; all items remain quarantined.', 'No files, archives, payloads, contributors, or code were fetched or executed.']}
    repositories = []
    seen = set()
    for page in range(1, 4):
        source = URL.format(page)
        raw = fetch(source, 1_000_000)
        if not isinstance(raw, bytes) or len(raw) > 1_000_000:
            raise ValueError('Page exceeds byte bound')
        collected = utc()
        values = json.loads(raw)
        if not isinstance(values, list) or len(values) > 100:
            raise ValueError('Invalid repository page')
        page_sha = hashlib.sha256(raw).hexdigest()
        report['pages'].append({'url': source, 'sha256': page_sha, 'bytes': len(raw), 'records': len(values), 'retrieved_at': collected})
        for value in values:
            try:
                normalized = sanitize(value)
            except (ValueError, TypeError, AttributeError):
                report['rejected'] += 1
                continue
            if normalized['full_name'] in seen:
                continue
            seen.add(normalized['full_name'])
            object_sha = hashlib.sha256(packed(value).encode()).hexdigest()
            evidence = store.ingest({'source_url': normalized['html_url'], 'source_item_id': normalized['full_name'], 'retrieved_at': collected, 'content_sha256': object_sha, 'normalized': normalized, 'publication_at': None, 'license': {'status': 'unknown', 'declared_spdx': normalized['declared_spdx']}, 'method': 'fixed official GitHub organization API GET; metadata only', 'worker': 'software', 'task_routes': [], 'limitations': report['limitations'], 'corrections': ['Repository creation time is retained as created_at; it does not establish publication time.'], 'provenance': {'primary_source': True, 'visibility': 'all_registered_roles', 'retrieval_kind': 'current_retrieval', 'source_page': source, 'source_page_sha256': page_sha, 'hash_basis': 'SHA256 of canonical JSON serialization of original repository object; not raw page bytes', 'raw_retained': False, 'intended_use': 'reference_only'}, 'privacy_review': 'pending', 'synthetic_status': 'unknown'})
            repositories.append(dict(normalized, source_page=source, source_page_sha256=page_sha, collected_at=collected, evidence=evidence))
            report['quarantined'] += 1
        if len(values) < 100:
            break
        if page == 3:
            report['truncated'] = True
    report['retrieved_at'] = utc()
    report['items'] = len(repositories)
    snapshot = {'report': report, 'repositories': repositories}
    encoded = (packed(snapshot) + '\n').encode()
    sha = hashlib.sha256(encoded).hexdigest()
    parent = Path(store_root).absolute().parent
    directory = parent / 'hak5-catalogs'
    directory.mkdir(exist_ok=True, mode=0o700)
    target = directory / (sha + '.json')
    with target.open('xb') as handle:
        handle.write(encoded)
    os.chmod(target, 0o600)
    pointer = {'snapshot': 'hak5-catalogs/' + target.name, 'sha256': sha, 'collected_at': collected}
    temporary = parent / ('hak5-current-' + sha + '.tmp')
    temporary.write_text(packed(pointer) + '\n')
    os.chmod(temporary, 0o600)
    temporary.replace(parent / 'hak5-current.json')
    return dict(report, source_snapshot=pointer['snapshot'], snapshot_sha256=sha)


def search(query, root=DEFAULT_ROOT, limit=5):
    if not isinstance(query, str) or len(query) > 1000 or type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError('Invalid catalog query')
    root = Path(root)
    pointer = root / 'hak5-current.json'
    if not pointer.exists():
        return []
    selected = json.loads(pointer.read_text())
    relative = selected['snapshot']
    if not re.fullmatch(r'hak5-catalogs/[a-f0-9]{64}\.json', relative):
        raise ValueError('Invalid catalog pointer')
    raw = (root / relative).read_bytes()
    if len(raw) > 3_000_000 or hashlib.sha256(raw).hexdigest() != selected['sha256']:
        raise ValueError('Catalog integrity check failed')
    terms = set(re.findall(r'\w+', query.lower()))
    results = []
    for value in json.loads(raw)['repositories']:
        tokens = set(re.findall(r'\w+', (value['full_name'] + ' ' + (value['description'] or '')).lower()))
        score = len(terms & tokens)
        if score:
            results.append({'name': value['full_name'], 'distribution': 'Hak5 / reference only', 'url': value['html_url'], 'score': score, 'score_kind': 'lexical token matches, not probability', 'description': value['description'], 'source_snapshot': relative, 'source_page_sha256': value['source_page_sha256'], 'collected_at': value['collected_at'], 'retrieval_kind': 'stored_snapshot', 'evidence_status': 'quarantine'})
    return sorted(results, key=lambda value: (-value['score'], value['name']))[:limit]
