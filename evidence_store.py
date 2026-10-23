"""Versioned staging evidence. Admission is a recorded human decision, never training."""
import hashlib
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def stamp(value):
    if not isinstance(value,str):
        raise ValueError('timestamp must be a string')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamp requires timezone')
    return parsed.astimezone(timezone.utc).isoformat()


def source_date(value):
    """Preserve published calendar-date precision rather than inventing a time."""
    if not isinstance(value,str):
        raise ValueError('source date must be an ISO date or zoned timestamp string')
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
        date.fromisoformat(value)
        return value
    return stamp(value)


class EvidenceStore:
    def __init__(self, root, max_records=10000, retention_days=30):
        self.root = Path(root).absolute()
        if self.root.is_symlink():
            raise ValueError('evidence root cannot be a symlink')
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.raw = self.root / 'raw'
        if self.raw.is_symlink():
            raise ValueError('raw directory cannot be a symlink')
        self.raw.mkdir(exist_ok=True)
        os.chmod(self.raw, 0o700)
        self.root_identity = (self.root.stat().st_dev, self.root.stat().st_ino)
        self.raw_identity = (self.raw.stat().st_dev, self.raw.stat().st_ino)
        self.db = self.root / 'evidence.sqlite3'
        self.max_records = max_records
        self.retention_days = retention_days
        with self.connect() as con:
            con.executescript('''
            CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, source_url TEXT, source_item_id TEXT,
              created_at TEXT NOT NULL, deleted_at TEXT, deletion_reason TEXT);
            CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY, record_id TEXT NOT NULL, sha TEXT,
              normalized TEXT, metadata TEXT, cluster TEXT, status TEXT NOT NULL, created_at TEXT,
              raw_path TEXT, deleted INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS retrievals(id INTEGER PRIMARY KEY, record_id TEXT, version_id TEXT,
              retrieved_at TEXT, method TEXT, worker TEXT, provenance TEXT);
            CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY, record_id TEXT, version_id TEXT,
              decision TEXT, reviewer TEXT, note TEXT, checks TEXT, reviewed_at TEXT);
            CREATE TABLE IF NOT EXISTS manifests(id TEXT PRIMARY KEY, name TEXT, kind TEXT,
              approved_by TEXT, created_at TEXT, snapshot TEXT, sha TEXT, valid INTEGER DEFAULT 1,
              invalidation_reason TEXT);
            CREATE TABLE IF NOT EXISTS members(manifest_id TEXT, record_id TEXT, version_id TEXT,
              cluster TEXT, kind TEXT, PRIMARY KEY(manifest_id,version_id));
            CREATE TABLE IF NOT EXISTS tombstones(record_id TEXT PRIMARY KEY, deleted_at TEXT, reason TEXT);
            CREATE INDEX IF NOT EXISTS version_record ON versions(record_id);
            CREATE INDEX IF NOT EXISTS version_cluster ON versions(cluster);
            CREATE INDEX IF NOT EXISTS retrieval_version_time ON retrievals(version_id,retrieved_at);
            ''')
        os.chmod(self.db, 0o600)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.db, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA secure_delete=ON')
        try:
            con.execute('BEGIN IMMEDIATE')
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    @staticmethod
    def tokens(normalized):
        # Bounded lexical similarity is a duplicate lead, not truth arbitration.
        text = packed(normalized).lower()
        return set(re.findall(r'[\w]+', text[:100000]))

    def ingest(self, record, raw=None):
        r = dict(record)
        source = r.get('source_url')
        if not isinstance(source, str) or not source or len(source) > 4096:
            raise ValueError('source_url required')
        url = urlsplit(source)
        if url.username or url.password:
            raise ValueError('credential-bearing source URLs prohibited')
        retrieved = stamp(r['retrieved_at'])
        normalized = r.get('normalized')
        if not isinstance(normalized, dict) or len(packed(normalized).encode()) > 262144:
            raise ValueError('normalized must be a bounded object')
        sha = r.get('content_sha256')
        if not isinstance(sha, str) or not re.fullmatch('[a-f0-9]{64}', sha):
            raise ValueError('original content_sha256 required')
        if raw is not None and (not isinstance(raw, bytes) or len(raw) > 4*1024*1024 or digest(raw) != sha):
            raise ValueError('raw bytes exceed bound or disagree with original digest')
        item = r.get('source_item_id', source)
        if not isinstance(item, str) or len(item) > 4096:
            raise ValueError('invalid source_item_id')
        rid = digest(packed([source, item]))
        # Include source-reported metadata: changed claims cannot overwrite prior versions.
        metadata = {k:r.get(k) for k in ('publication_at','event_at','license','method','worker',
          'task_routes','limitations','provenance','privacy_review','synthetic_status','label_origin',
          'corrections','supersedes','conflicting_claims','training_task','extraction_schema')}
        for key in ('publication_at','event_at'):
            if metadata[key] is not None:
                metadata[key] = source_date(metadata[key])
        metadata['license'] = metadata['license'] or {'status':'unknown'}
        metadata['privacy_review'] = metadata['privacy_review'] or 'pending'
        metadata['synthetic_status'] = metadata['synthetic_status'] or 'unknown'
        if len(packed(metadata).encode()) > 65536:
            raise ValueError('metadata exceeds bound')
        vid = digest(packed([rid, sha, normalized, metadata]))
        with self.connect() as con:
            if con.execute('SELECT 1 FROM tombstones WHERE record_id=?',(rid,)).fetchone():
                raise ValueError('deleted identity cannot be reingested')
            existing = con.execute('SELECT 1 FROM records WHERE id=?',(rid,)).fetchone()
            if not existing and con.execute('SELECT count(*) FROM records').fetchone()[0] >= self.max_records:
                raise ValueError('record capacity reached')
            if con.execute('SELECT count(*) FROM retrievals').fetchone()[0] >= self.max_records*20:
                raise ValueError('retrieval capacity reached')
            if con.execute('SELECT count(*) FROM versions').fetchone()[0] >= self.max_records*5:
                raise ValueError('version capacity reached')
            con.execute('INSERT OR IGNORE INTO records VALUES(?,?,?,?,NULL,NULL)',(rid,source,item,utc()))
            previous = con.execute('SELECT * FROM versions WHERE id=?',(vid,)).fetchone()
            if previous:
                cluster = previous['cluster']
            else:
                cluster = vid
                matches = set()
                tokens = self.tokens(normalized)
                for candidate in con.execute('SELECT id,record_id,sha,normalized,cluster FROM versions WHERE deleted=0'):
                    other = self.tokens(json.loads(candidate['normalized']))
                    if candidate['record_id'] == rid or candidate['sha'] == sha or (len(tokens)>=12 and len(other)>=12 and
                        len(tokens & other)/max(1,len(tokens | other)) >= .9):
                        matches.add(candidate['cluster'])
                if matches:
                    cluster = min(matches)
                    for old in matches:
                        con.execute('UPDATE versions SET cluster=? WHERE cluster=?',(cluster,old))
                        con.execute('UPDATE members SET cluster=? WHERE cluster=?',(cluster,old))
                    if con.execute('SELECT count(DISTINCT kind) FROM members WHERE cluster=?',(cluster,)).fetchone()[0] > 1:
                        con.execute("UPDATE manifests SET valid=0,invalidation_reason='duplicate cluster merged across split boundary' WHERE id IN (SELECT manifest_id FROM members WHERE cluster=?)",(cluster,))
                con.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?,?,?,0)',
                  (vid,rid,sha,packed(normalized),packed(metadata),cluster,'quarantine',utc(),None))
            if raw is not None:
                path = self.raw / (vid+'.bin')
                with self.raw_directory() as directory:
                    try:
                        fd = os.open(vid+'.bin', os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory)
                    except FileExistsError:
                        fd = os.open(vid+'.bin',os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory)
                        with os.fdopen(fd,'rb') as handle:
                            retained=handle.read(4*1024*1024+1)
                        if len(retained)>4*1024*1024 or digest(retained)!=sha:
                            raise ValueError('retained raw content fails integrity check')
                    else:
                        with os.fdopen(fd,'wb') as handle:
                            handle.write(raw)
                con.execute('UPDATE versions SET raw_path=? WHERE id=?',(str(path),vid))
            con.execute('INSERT INTO retrievals(record_id,version_id,retrieved_at,method,worker,provenance) VALUES(?,?,?,?,?,?)',
              (rid,vid,retrieved,r.get('method'),r.get('worker'),packed(r.get('provenance',{}))))
            status = con.execute('SELECT status FROM versions WHERE id=?',(vid,)).fetchone()[0]
        return {'record_id':rid,'version_id':vid,'status':status,'duplicate_cluster_id':cluster,'is_duplicate':bool(previous or (not previous and matches)), 'training_occurred':False}

    def summary(self):
        with self.connect() as con:
            counts = {r[0]:r[1] for r in con.execute('SELECT status,count(*) FROM versions WHERE deleted=0 GROUP BY status')}
            return {'records':con.execute('SELECT count(*) FROM records WHERE deleted_at IS NULL').fetchone()[0],
              'versions_by_status':counts,'retrievals':con.execute('SELECT count(*) FROM retrievals').fetchone()[0],
              'datasets':con.execute('SELECT count(*) FROM manifests').fetchone()[0],
              'invalidated_datasets':con.execute('SELECT count(*) FROM manifests WHERE valid=0').fetchone()[0],
              'training_occurred':False,'retention_days':self.retention_days,'max_records':self.max_records,
              'near_duplicate_method':'bounded lexical Jaccard >=0.90 with >=12 tokens; heuristic, incomplete'}

    def list_records(self, limit=100, include_normalized=True):
        if not isinstance(limit,int) or not 1 <= limit <= 1000:
            raise ValueError('limit must be 1..1000')
        if not isinstance(include_normalized,bool):
            raise ValueError('include_normalized must be boolean')
        with self.connect() as con:
            columns='r.id record_id,r.source_url,r.source_item_id,v.id version_id,v.sha content_sha256,v.status,v.cluster duplicate_cluster_id,v.metadata'
            if include_normalized:
                columns+=',v.normalized'
            columns+=', (SELECT MAX(t.retrieved_at) FROM retrievals t WHERE t.version_id=v.id) retrieved_at'
            rows=con.execute('SELECT '+columns+' FROM records r JOIN versions v ON r.id=v.record_id WHERE v.deleted=0 ORDER BY v.created_at DESC LIMIT ?',(limit,)).fetchall()
            result=[]
            for row in rows:
                item=dict(row,metadata=json.loads(row['metadata']))
                if include_normalized:
                    item['normalized']=json.loads(row['normalized'])
                result.append(item)
            return result

    def review(self, record_id, version_id, decision, reviewer, note, checks):
        choices = {'accept_reference':'accepted_reference','accept_training':'accepted_training',
                   'reject':'rejected','quarantine':'quarantine'}
        if decision not in choices or not isinstance(checks,dict) or not reviewer or not note:
            raise ValueError('explicit decision, reviewer, note and checks required')
        with self.connect() as con:
            row = con.execute('SELECT * FROM versions WHERE id=? AND record_id=? AND deleted=0',(version_id,record_id)).fetchone()
            if not row:
                raise ValueError('unknown active evidence version')
            meta = json.loads(row['metadata'])
            if decision.startswith('accept_'):
                required = ['provenance_valid','license_permits_use','privacy_reviewed']
                if decision == 'accept_training':
                    required += ['real_data_reviewed','labels_valid','dataset_eligible','schema_valid','features_complete']
                    if any(not isinstance(meta.get(k),str) or not meta[k].strip() for k in ('training_task','extraction_schema')):
                        raise ValueError('explicit training_task and extraction_schema required')
                    origin = meta.get('label_origin')
                    if origin not in ('human_verified','instrument_measurement','official_record'):
                        raise ValueError('documented non-model label origin required')
                    if meta['synthetic_status'] not in ('documented_measurement','documented_public_record','authorized_observation'):
                        raise ValueError('documented genuine-data provenance required for operational training')
                if any(checks.get(key) is not True for key in required):
                    raise ValueError('required review checks missing')
                if meta['license'].get('status') != 'verified':
                    raise ValueError('verified license evidence required; ingest a corrected version')
            con.execute('INSERT INTO reviews(record_id,version_id,decision,reviewer,note,checks,reviewed_at) VALUES(?,?,?,?,?,?,?)',
              (record_id,version_id,decision,reviewer,note,packed(checks),utc()))
            con.execute('UPDATE versions SET status=? WHERE id=?',(choices[decision],version_id))
            if decision in ('reject','quarantine') or (row['status']=='accepted_training' and decision!='accept_training'):
                con.execute("UPDATE manifests SET valid=0,invalidation_reason='evidence review revoked' WHERE id IN (SELECT manifest_id FROM members WHERE version_id=?)",(version_id,))
        return {'record_id':record_id,'version_id':version_id,'status':choices[decision],'training_occurred':False}

    def freeze_dataset(self, name, kind, record_versions, approved_by):
        if kind not in ('training','evaluation') or not name or not approved_by or not record_versions:
            raise ValueError('name, explicit approval, kind and members required')
        if len(record_versions)>self.max_records:
            raise ValueError('dataset capacity exceeded')
        with self.connect() as con:
            members=[]
            contracts=set()
            for member in record_versions:
                row=con.execute('SELECT * FROM versions WHERE id=? AND record_id=? AND deleted=0',
                  (member['version_id'],member['record_id'])).fetchone()
                if not row or row['status']!='accepted_training':
                    raise ValueError('every dataset member requires training-quality admission')
                meta=json.loads(row['metadata'])
                contracts.add((meta.get('training_task'),meta.get('extraction_schema')))
                conflict=con.execute('SELECT 1 FROM members WHERE kind<>? AND (cluster=? OR record_id=?)',
                  (kind,row['cluster'],row['record_id'])).fetchone()
                if conflict:
                    raise ValueError('frozen identity or duplicate cluster crosses evaluation/training boundary')
                members.append({'record_id':row['record_id'],'version_id':row['id'],
                  'content_sha256':row['sha'],'duplicate_cluster_id':row['cluster']})
            if len(contracts)!=1:
                raise ValueError('dataset members must share task and extraction schema')
            if len({m['version_id'] for m in members})!=len(members):
                raise ValueError('duplicate dataset member')
            task,schema=next(iter(contracts))
            snapshot={'training_task':task,'extraction_schema':schema,'training_ready':False,
              'limitation':'Evidence membership only; extraction, feature validation and model training remain unexecuted.', 'name':name,'kind':kind,'approved_by':approved_by,'created_at':utc(),'members':members}
            serialized=packed(snapshot); mid=digest(serialized)
            con.execute('INSERT INTO manifests VALUES(?,?,?,?,?,?,?,1,NULL)',
              (mid,name,kind,approved_by,snapshot['created_at'],serialized,digest(serialized)))
            con.executemany('INSERT INTO members VALUES(?,?,?,?,?)',
              [(mid,m['record_id'],m['version_id'],m['duplicate_cluster_id'],kind) for m in members])
        return dict(snapshot,manifest_id=mid,sha256=mid,valid=True,training_occurred=False)

    def trace(self, record_id, limit=20, offset=0):
        if not isinstance(limit,int) or not 1<=limit<=100 or not isinstance(offset,int) or offset<0:
            raise ValueError('trace limit must be 1..100 and offset nonnegative')
        with self.connect() as con:
            queries={
              'versions':('SELECT * FROM versions WHERE record_id=? ORDER BY created_at,id', 'SELECT count(*) FROM versions WHERE record_id=?'),
              'retrievals':('SELECT * FROM retrievals WHERE record_id=? ORDER BY id', 'SELECT count(*) FROM retrievals WHERE record_id=?'),
              'reviews':('SELECT * FROM reviews WHERE record_id=? ORDER BY id', 'SELECT count(*) FROM reviews WHERE record_id=?'),
              'datasets':('SELECT DISTINCT m.id,m.kind,m.valid,m.invalidation_reason FROM manifests m JOIN members n ON m.id=n.manifest_id WHERE n.record_id=? ORDER BY m.id', 'SELECT count(DISTINCT manifest_id) FROM members WHERE record_id=?')}
            tomb=con.execute('SELECT * FROM tombstones WHERE record_id=?',(record_id,)).fetchone()
            if tomb:
                queries={'datasets':queries['datasets']}
                result={'tombstone':dict(tomb)}
            else:
                record=con.execute('SELECT * FROM records WHERE id=?',(record_id,)).fetchone()
                if not record:
                    raise ValueError('unknown record')
                result={'record':dict(record)}
            coverage={}
            for key,(query,count) in queries.items():
                total=con.execute(count,(record_id,)).fetchone()[0]
                rows=[dict(x) for x in con.execute(query+' LIMIT ? OFFSET ?',(record_id,limit,offset))]
                if key=='versions':
                    for row in rows:
                        row['metadata']=json.loads(row['metadata'])
                        row['normalized']=json.loads(row['normalized'])
                result[key]=rows
                coverage[key]={'total':total,'returned':len(rows),'offset':offset,'has_more':offset+len(rows)<total}
            result['coverage']=coverage
            return result

    @contextmanager
    def raw_directory(self):
        flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
        root_fd=os.open(self.root,flags)
        raw_fd=None
        try:
            st=os.fstat(root_fd)
            if (st.st_dev,st.st_ino)!=self.root_identity:
                raise ValueError('evidence root ownership changed')
            raw_fd=os.open('raw',flags,dir_fd=root_fd)
            st=os.fstat(raw_fd)
            if (st.st_dev,st.st_ino)!=self.raw_identity:
                raise ValueError('raw directory ownership changed')
            yield raw_fd
        finally:
            if raw_fd is not None:
                os.close(raw_fd)
            os.close(root_fd)

    def delete_record(self, record_id, reason):
        if not reason:
            raise ValueError('deletion reason required')
        with self.connect() as con:
            row=con.execute('SELECT * FROM records WHERE id=?',(record_id,)).fetchone()
            if not row:
                raise ValueError('unknown record')
            # Raw deletion precedes metadata removal: failures retain cleanup ownership for retry.
            for v in con.execute('SELECT id,raw_path FROM versions WHERE record_id=?',(record_id,)):
                if v['raw_path']:
                    expected=self.raw/(v['id']+'.bin')
                    if Path(v['raw_path'])!=expected:
                        raise ValueError('persisted raw path disagrees with owner-derived identity')
                    with self.raw_directory() as directory:
                        try:
                            os.unlink(v['id']+'.bin',dir_fd=directory)
                        except FileNotFoundError:
                            pass
            now=utc()
            con.execute('INSERT OR IGNORE INTO tombstones VALUES(?,?,?)',(record_id,now,reason))
            con.execute('UPDATE records SET source_url=NULL,source_item_id=NULL,deleted_at=?,deletion_reason=? WHERE id=?',(now,reason,record_id))
            con.execute("UPDATE versions SET normalized=NULL,metadata=NULL,sha=NULL,raw_path=NULL,status='deleted',deleted=1 WHERE record_id=?",(record_id,))
            con.execute('DELETE FROM retrievals WHERE record_id=?',(record_id,))
            con.execute('DELETE FROM reviews WHERE record_id=?',(record_id,))
            con.execute("UPDATE manifests SET valid=0,invalidation_reason='member deleted',snapshot=NULL WHERE id IN (SELECT manifest_id FROM members WHERE record_id=?)",(record_id,))
        return {'record_id':record_id,'deleted':True,'affected_manifests_invalidated':True}

    def expire_retention(self, now_utc):
        cutoff=(datetime.fromisoformat(stamp(now_utc))-timedelta(days=self.retention_days)).isoformat()
        with self.connect() as con:
            ids=[r[0] for r in con.execute('SELECT id FROM records WHERE deleted_at IS NULL AND created_at<?',(cutoff,))]
        results=[self.delete_record(rid,'retention expired') for rid in ids]
        return {'expired_records':len(results),'results':results}
