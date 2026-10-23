"""Exact official API/archive policy and bounded credential-free transport."""
import base64
import gzip
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler, urlopen
from public_sources import SOURCES
from artifact_catalog import TOOLS

MAX_BYTES = 25_000_000
DEADLINE_SECONDS = 25
API_URLS = frozenset(SOURCES.values()) | {
    *{f'https://api.github.com/orgs/hak5/repos?type=public&per_page=100&page={page}' for page in range(1, 4)},
    'https://archive.ics.uci.edu/api/dataset?id=422',
    'https://archive.ics.uci.edu/api/dataset?id=855',
    'https://api.github.com/repos/curl/curl/releases/latest',
    'https://api.github.com/repos/openssl/openssl/releases/latest',
}
REPOS = frozenset(value['repo'].lower() for value in TOOLS.values())


def validate(url):
    if not isinstance(url, str):
        raise ValueError('Unapproved source URL')
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme == 'https' and parsed.port in {None, 443} and not parsed.username and not parsed.password and not parsed.fragment
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('Unapproved source URL')
    if url in API_URLS:
        return
    if parsed.hostname in {'api.github.com','api.stackexchange.com'}:
        from role_research import allowed_url
        if allowed_url(url):return
    if parsed.query:
        raise ValueError('Unapproved source query')
    parts = parsed.path.strip('/').split('/')
    if parsed.hostname == 'api.github.com' and len(parts) == 5 and parts[0] == 'repos' and '/'.join(parts[1:3]).lower() in REPOS and parts[3:] == ['commits', 'HEAD']:
        return
    if parsed.hostname == 'codeload.github.com' and len(parts) == 4 and '/'.join(parts[:2]).lower() in REPOS and parts[2] == 'tar.gz' and re.fullmatch('[a-f0-9]{40}', parts[3]):
        return
    raise ValueError('Unapproved source URL')


class Redirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def direct_fetch(url, bound):
    """Worker-only retrieval; its parent supplies the total deadline."""
    validate(url)
    if type(bound) is not int or not 1 <= bound <= MAX_BYTES:
        raise ValueError('Invalid download bound')
    opener = build_opener(ProxyHandler({}), Redirects())
    with opener.open(Request(url, headers={'User-Agent': 'LocalResearchLab/1.0', 'Accept': 'application/json'}), timeout=10) as response:
        value = response.read(bound + 1)
        encoding=response.headers.get('Content-Encoding','').lower()
    if len(value) > bound:
        raise ValueError('Source exceeds download bound')
    if encoding=='gzip' or value[:2]==b'\x1f\x8b':
        with gzip.GzipFile(fileobj=io.BytesIO(value)) as stream:value=stream.read(bound+1)
        if len(value)>bound:raise ValueError('Decompressed source exceeds download bound')
    elif encoding not in ('','identity'):
        raise ValueError('Unsupported source content encoding')
    return value


def fetch(url, bound):
    validate(url)
    if type(bound) is not int or not 1 <= bound <= MAX_BYTES:
        raise ValueError('Invalid download bound')
    if os.environ.get('LAB_CONTAINER') == '1':
        token = Path('/run/secrets/broker_token').read_text().strip()
        request = Request('http://imports:8791/fetch', data=json.dumps({'url': url, 'bound': bound}).encode(), headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        max_response = ((bound + 2) // 3) * 4 + 8192
        with urlopen(request, timeout=35) as response:
            raw = response.read(max_response + 1)
        if len(raw) > max_response:
            raise ValueError('Import broker response exceeds bound')
        value = base64.b64decode(json.loads(raw)['data'], validate=True)
    else:
        # run(timeout=...) kills and waits for the sole worker on expiration.
        result = subprocess.run([sys.executable, '-I', str(Path(__file__).with_name('source_fetch_worker.py'))], input=json.dumps({'url': url, 'bound': bound}).encode(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=DEADLINE_SECONDS, check=True, env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'})
        value = result.stdout
    if len(value) > bound:
        raise ValueError('Source exceeds download bound')
    return value
