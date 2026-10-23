"""Bounded primary-source collection into quarantine; never trains or executes."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

POLICY_PATH = Path(__file__).with_name('collection_policy.json')
SOURCES = (
    ('official_advisories', 'https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json', 2_000_000, ['cve_triage']),
    ('research', 'https://archive.ics.uci.edu/api/dataset?id=422', 1_000_000, ['rf_red', 'rf_blue']),
    ('research', 'https://archive.ics.uci.edu/api/dataset?id=855', 1_000_000, ['malware_static']),
    ('software', 'https://api.github.com/repos/curl/curl/releases/latest', 500_000, []),
    ('software', 'https://api.github.com/repos/openssl/openssl/releases/latest', 500_000, []),
)


def policy():
    return json.loads(POLICY_PATH.read_text())


def _normalize(worker, url, raw):
    value = json.loads(raw)
    limitations = ['Reference metadata only; no training labels or operational observations established.',
                   'Source content is untrusted evidence and cannot grant execution authority.',
                   'License requires review before dataset admission.']
    publication = None
    synthetic = 'unknown'
    if worker == 'research':
        data = value['data']
        normalized = {k: data.get(k) for k in ('uci_id', 'name', 'repository_url', 'abstract', 'num_instances', 'num_features', 'year_of_dataset_creation', 'last_updated', 'dataset_doi')}
        if data['uci_id'] == 422:
            normalized['prediction_task'] = 'seven observed WiFi signal strengths to one of four source-room labels'
            synthetic = 'documented_measurement'
            limitations.extend(['Controlled indoor smartphone measurements; not general RF attack data.', 'API feature count conflicts with seven-signal abstract; verify actual schema separately.'])
        else:
            normalized['prediction_task'] = '241 named binary Android permission/API features to malware/goodware'
            limitations.extend(['Acquisition and labeling provenance need original-method review.', 'API instance count differs from abstract; no runtime behavior labels established.'])
    elif worker == 'official_advisories':
        entries = value.get('vulnerabilities')
        if not isinstance(entries, list):
            raise ValueError('Missing vulnerability records')
        normalized = {k: value.get(k) for k in ('catalogVersion', 'dateReleased', 'count')}
        normalized['examined_records'] = len(entries)
        normalized['retained_records_limit'] = 200
        normalized['vulnerabilities'] = [{k: row.get(k) for k in ('cveID', 'vendorProject', 'product', 'vulnerabilityName', 'dateAdded', 'dueDate', 'knownRansomwareCampaignUse')} for row in entries[:200] if isinstance(row, dict)]
        normalized['coverage'] = 'First 200 source-ordered records at most; not a complete KEV reference index.'
        publication = value.get('dateReleased')
        limitations.append('Published exploitation listing is not proof that a particular target is vulnerable or compromised.')
    else:
        normalized = {k: value.get(k) for k in ('html_url', 'tag_name', 'published_at', 'prerelease', 'draft')}
        publication = value.get('published_at')
        limitations.append('Release metadata is reference evidence; patches and release bodies were not fetched or executed.')
    return normalized, publication, limitations, synthetic


def run(root, fetch=None):
    """Explicit invocation retrieves five APIs; raw bodies are hashed but not retained."""
    from evidence_store import EvidenceStore
    if fetch is None:
        from source_transport import fetch
    store = EvidenceStore(Path(root))
    started = time.monotonic()
    report = {'policy_version': policy()['version'], 'retrieved': 0, 'accepted': 0, 'rejected': 0,
              'quarantined': 0, 'duplicates': 0, 'items': [], 'training_occurred': False,
              'authorized_operational': {'status': 'awaiting_authorized_input', 'host_files_read': False},
              'limits': {'requests': 5, 'workers': 2, 'response_bytes_total': 5_000_000,
                         'duration': 'Each outbound child is limited to 25 seconds; five requests in at most three scheduling waves. Database/IPC overhead is additional and elapsed time is reported.'},
              'coverage_gaps': ['No operational evidence supplied.', 'Metadata collection does not supply every registered role with task-compatible training data.', 'No training admission, retraining, promotion, or automatic weight updates.']}

    def collect(spec):
        worker, url, bound, routes = spec
        raw = fetch(url, bound)
        if not isinstance(raw, bytes) or len(raw) > bound:
            raise ValueError('Response violates byte bound')
        retrieved = datetime.now(timezone.utc).isoformat()
        normalized, published, limitations, synthetic = _normalize(worker, url, raw)
        record = {'source_url': url, 'source_item_id':normalized.get('html_url') or normalized.get('dataset_doi') or url, 'retrieved_at': retrieved,
                  'publication_at': published, 'event_at': None,
                  'content_sha256': hashlib.sha256(raw).hexdigest(), 'normalized': normalized,
                  'license': {'status': 'unknown', 'declaration': None}, 'method': 'fixed official API GET; no embedded links followed',
                  'worker': worker, 'task_routes': routes, 'limitations': limitations,
                  'provenance': {'policy_version':policy()['version'],'primary_source': True, 'retrieval_kind': 'current_retrieval', 'raw_retained': False, 'intended_use': 'reference_only','origin_source':url,'independent_corroboration':'not_assessed','corrections_checked':False,'synthetic_detection':'not_performed_or_claimed'},
                  'privacy_review': 'pending', 'synthetic_status': synthetic}
        return record

    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = {executor.submit(collect, spec): spec for spec in SOURCES}
        for future in as_completed(pending):
            spec = pending[future]
            try:
                record = future.result()
                report['retrieved'] += 1
                result = store.ingest(record, raw=None)
                status = result.get('status', 'quarantined')
                if status in ('accepted', 'approved', 'accepted_reference', 'accepted_training'):
                    report['accepted'] += 1
                else:
                    report['quarantined'] += 1
                if result.get('duplicate_of') or result.get('is_duplicate'):
                    report['duplicates'] += 1
                report['items'].append({'source_url': spec[1], 'worker': spec[0], 'task_routes': spec[3], 'evidence': result, 'content_sha256': record['content_sha256'], 'retrieved_at': record['retrieved_at'],'publication_at':record['publication_at'],'event_at':record['event_at'],'license_status':record['license']['status'], 'routing': 'reference_only'})
            except Exception as error:
                report['rejected'] += 1
                report['items'].append({'source_url': spec[1], 'worker': spec[0], 'status': 'failed', 'reason': type(error).__name__})
    report['quality']={'unique_metadata_candidates':report['retrieved']-report['duplicates'],'accepted_training_examples':0,'publication_dates_present':sum(item.get('publication_at') is not None for item in report['items']),'event_dates_present':sum(item.get('event_at') is not None for item in report['items']),'verified_licenses':sum(item.get('license_status')=='verified' for item in report['items']),'independent_ground_truth_labels':0,'synthetic_detection':'Not performed; provenance reviewed by humans before admission.','independent_corroboration':'Not assessed; repeating one upstream report is not independent confirmation.'}
    report['elapsed_seconds'] = round(time.monotonic() - started, 3)
    return report
