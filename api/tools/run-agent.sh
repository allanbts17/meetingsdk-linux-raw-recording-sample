#!/bin/bash
set -e
/app/demo/setup-pulseaudio.sh
exec python3 -m uvicorn app.private_http:app_factory --factory --host 0.0.0.0 --port 8080 --no-access-log "$@"
