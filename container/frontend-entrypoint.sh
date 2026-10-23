#!/bin/sh
# Resolve service names through this container's DNS on either Podman or Docker.
# The image root is read-only; generated configuration belongs in the /tmp tmpfs.
set -eu

resolver_file=${AZRAEL_RESOLV_CONF:-/etc/resolv.conf}
template=${AZRAEL_NGINX_TEMPLATE:-/etc/nginx/azrael-nginx.conf.template}
generated=${AZRAEL_NGINX_CONFIG:-/tmp/azrael-nginx.conf}
resolvers=$(awk '
    $1 == "nameserver" && split($2, octets, ".") == 4 {
        valid = 1
        for (i = 1; i <= 4; i++) {
            if (octets[i] !~ /^[0-9]+$/ || octets[i] + 0 > 255) valid = 0
        }
        if (valid && !seen[$2]++) printf "%s ", $2
    }
' "$resolver_file")
if [ -z "$resolvers" ]; then
    echo "AZRAEL frontend requires an IPv4 DNS nameserver in its resolver configuration" >&2
    exit 1
fi
sed "s/@AZRAEL_DNS_RESOLVERS@/$resolvers/g" "$template" > "$generated"
exec nginx -c "$generated" "$@"
