#!/bin/sh
exec wget -q -O /dev/null --timeout=3 http://127.0.0.1:8080/healthz
