"""Conservative, read-only Podman writable-layer audit helpers."""
import argparse
import json
import sys


INJECTED_PATH_CHANGES = {
    "A /etc/hosts", "C /etc/hosts",
    "A /etc/resolv.conf", "C /etc/resolv.conf",
    "A /etc/hostname", "C /etc/hostname",
}


def started_at_is_zero(value):
    value = (value or "").strip()
    return not value or value == "0" or value.startswith("0001-01-01T00:00:00")


def audit_diff(started_at, diff_output):
    """Skip never-started layers; otherwise allow only Podman injected /etc entries."""
    if started_at_is_zero(started_at):
        return {"status": "skipped_never_started", "started_at": started_at,
                "ignored_entries": [], "unexpected_entries": []}
    entries = [line.strip() for line in (diff_output or "").splitlines() if line.strip()]
    ignored = [line for line in entries if line == "C /etc" or line in INJECTED_PATH_CHANGES]
    unexpected = [line for line in entries if line not in ignored]
    return {"status": "blocked" if unexpected else "clean", "started_at": started_at,
            "ignored_entries": ignored, "unexpected_entries": unexpected}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("started_at")
    parser.add_argument("--started-only", action="store_true",
                        help="print whether a writable-layer diff should be inspected")
    args = parser.parse_args()
    if args.started_only:
        print("never_started" if started_at_is_zero(args.started_at) else "started")
        return 0
    result = audit_diff(args.started_at, sys.stdin.read())
    print(json.dumps(result, sort_keys=True))
    return 1 if result["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
