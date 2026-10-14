#!/bin/bash
set -e
/app/demo/setup-pulseaudio.sh
exec python3 -m tools.agent_service "$@"
