"""Pinned official-source archives. Download/extract require separate admin approvals."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import tarfile
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parent
import storage_paths

from artifact_catalog import TOOLS
from source_transport import fetch

MAX_DOWNLOAD=25_000_000
MAX_EXPANDED=64_000_000
MAX_MEMBERS=10000

def request(tool,model,stage='download',parent=None):
    if tool not in TOOLS or stage not in {'download','extract','install','execute'}:
        raise ValueError('Select a curated tool and stage')
    value={'request_id':secrets.token_hex(12),'tool':tool,'model':model,'stage':stage,'repo':TOOLS[tool]['repo'],
           'status':'pending','section':TOOLS[tool]['section'],'uses_left':1,
           'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(),
           'executable':stage in {'download','extract'},'reason':'Source retrieval only; no trust or execution inferred from a hash.'}
    if stage=='download':
        metadata=json.loads(fetch('https://api.github.com/repos/'+value['repo']+'/commits/HEAD',128000))
        sha=metadata.get('sha')
        if not isinstance(sha,str) or not re.fullmatch('[a-f0-9]{40}',sha):raise ValueError('No immutable source revision')
        value['revision']=sha;value['url']='https://codeload.github.com/'+value['repo']+'/tar.gz/'+sha
    else:
        if not parent or parent.get('status')!='consumed' or parent['tool']!=tool or parent['model']!=model:
            raise ValueError('Select a completed prior stage for the same tool and model')
        if stage=='extract' and parent['stage']!='download':raise ValueError('Extraction needs a completed download')
        if stage in {'install','execute'} and parent['stage']!='extract':raise ValueError('Installation/execution planning needs completed extraction')
        value.update(parent_id=parent['request_id'],revision=parent['revision'],url=parent['url'],sha256=parent['sha256'])
        if stage in {'install','execute'}:
            value['reason']='Plan only: configure a disposable lab image/VM and explicit allowlisted command before enabling this stage. No host installer or elevated executor is connected.'
    return value


def download(value):
    data=fetch(value['url'],MAX_DOWNLOAD)
    folder=storage_paths.artifact_path(ROOT,value['request_id']);folder.mkdir(parents=True,exist_ok=False,mode=0o700)
    (folder/'manifest.json').write_text(json.dumps({'owner':'local-research-lab','request_id':value['request_id'],'stage':'download','state':'incomplete'})+'\n')
    path=folder/'source.tar.gz'
    with path.open('xb') as stream:stream.write(data)
    digest=hashlib.sha256(data).hexdigest()
    manifest={key:value[key] for key in ['request_id','tool','model','stage','repo','revision','url']}
    manifest.update(owner='local-research-lab',state='complete',sha256=digest,bytes=len(data),signature_verified=False,kind='source_archive',installed=False,executed=False)
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return {'sha256':digest,'artifact':str(path),'manifest':str(folder/'manifest.json'),'bytes':len(data),
            'limits':'Official repository snapshot pinned by commit; signature not verified. No extraction, installation or execution.'}


def extract(value,parent):
    path=storage_paths.artifact_path(ROOT,parent['request_id'],'source.tar.gz')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=value['sha256']:raise ValueError('Downloaded artifact changed')
    destination=storage_paths.artifact_path(ROOT,value['request_id']);destination.mkdir(parents=True,exist_ok=False,mode=0o700)
    (destination/'manifest.json').write_text(json.dumps({'owner':'local-research-lab','request_id':value['request_id'],'stage':'extract','state':'incomplete','parent_id':parent['request_id']})+'\n')
    with tarfile.open(path,'r:gz') as archive:
        members=[];expanded=0;seen=set()
        for member in archive:
            pieces=PurePosixPath(member.name)
            if (pieces.is_absolute() or '..' in pieces.parts or '\\' in member.name or '\x00' in member.name
                or not (member.isfile() or member.isdir()) or member.issym() or member.islnk() or member.sparse):
                raise ValueError('Archive contains unsupported paths, links or special files')
            normalized=str(pieces)
            if normalized in seen:raise ValueError('Archive has duplicate member paths')
            seen.add(normalized);expanded+=member.size
            if len(members)>=MAX_MEMBERS or expanded>MAX_EXPANDED or member.size<0:raise ValueError('Archive expansion exceeds bounds')
            members.append(member)
        for member in members:
            target=destination.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():target.mkdir(parents=True,exist_ok=True,mode=0o700);continue
            target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            source=archive.extractfile(member)
            if source is None:raise ValueError('Archive file has no content')
            fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with source,os.fdopen(fd,'wb') as stream:
                remaining=member.size
                while remaining:
                    data=source.read(min(65536,remaining))
                    if not data:raise ValueError('Truncated archive member')
                    stream.write(data);remaining-=len(data)
    result={'owner':'local-research-lab','state':'complete','request_id':value['request_id'],'sha256':value['sha256'],'directory':str(destination),'members':len(members),'expanded_bytes':expanded,
            'installed':False,'executed':False,'limits':'Source extracted as non-executable data. Links/special files are rejected. A failed extraction may leave owned partial data for inspection.'}
    (destination/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
