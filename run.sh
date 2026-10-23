#!/usr/bin/env bash
set -euo pipefail
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$project_dir"
if [[ $# -eq 0 ]]; then
    set -- --install --build --start --verify
fi
has_runtime=false
for argument in "$@"; do
    if [[ "$argument" == "--runtime" ]]; then has_runtime=true; break; fi
done
if [[ "$has_runtime" == true ]]; then
    exec python3 "$project_dir/setup_lab.py" "$@"
fi
exec python3 "$project_dir/setup_lab.py" --runtime auto "$@"
