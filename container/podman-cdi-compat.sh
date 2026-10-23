#!/bin/sh
# Run Podman in a private mount namespace with the user-owned CDI spec overlaid.
set -eu

spec_dir=$1
shift
if [ ! -d "$spec_dir" ] || [ ! -f "$spec_dir/nvidia.yaml" ]; then
    echo "AZRAEL CDI compatibility spec is missing: $spec_dir" >&2
    exit 2
fi

exec unshare --mount --propagation private sh -eu -c '
    mount --make-rprivate /
    mount --bind "$1" /etc/cdi
    mount --bind "$1" /var/run/cdi
    shift
    exec "$@"
' azrael-cdi "$spec_dir" "$@"
