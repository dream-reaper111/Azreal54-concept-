"""One stdlib outbound fetch; no subprocesses, execution, or credential inheritance."""
import json
from pathlib import Path
import sys
# -I excludes ambient import paths; load only this application's transport policy.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_transport import direct_fetch


def main():
    request = sys.stdin.buffer.read(4097)
    if len(request) > 4096:
        raise ValueError('Request exceeds bound')
    value = json.loads(request)
    if not isinstance(value, dict) or set(value) != {'url', 'bound'}:
        raise ValueError('Invalid source request')
    sys.stdout.buffer.write(direct_fetch(value['url'], value['bound']))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        sys.exit(1)
