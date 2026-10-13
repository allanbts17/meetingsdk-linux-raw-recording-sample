#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
    pause|resume|stop|status|quit) ;;
    *) echo "Usage: playback-control.sh pause|resume|stop|status|quit" >&2; exit 1 ;;
esac
if [[ ! -p /tmp/zoom-playback-control ]]; then
    echo "Playback command pipe not available; check that the participant is running." >&2
    exit 1
fi
# Timeout also detects an orphan FIFO with no reader.
timeout 3 bash -c 'printf "%s\n" "$1" > /tmp/zoom-playback-control' bash "$1"
