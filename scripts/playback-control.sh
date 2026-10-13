#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
    pause|resume|stop|status|quit) ;;
    play)
        [[ $# == 3 && "$2" =~ ^(video|video-silent|audio)$ && "$3" == /* && "$3" != *$'\n'* && "$3" != *$'\r'* ]] || {
            echo 'Usage: playback-control.sh play video|video-silent|audio /absolute/file' >&2; exit 1;
        }
        ;;
    *) echo "Usage: playback-control.sh pause|resume|stop|status|quit OR play video|video-silent|audio /absolute/file" >&2; exit 1 ;;
esac
if [[ ! -p /tmp/zoom-playback-control ]]; then
    echo "Playback command pipe not available; check that the participant is running." >&2
    exit 1
fi
# Timeout also detects an orphan FIFO with no reader.
command="$1"
if [[ "$1" == play ]]; then command="play $2 $3"; fi
timeout 3 bash -c 'printf "%s\n" "$1" > /tmp/zoom-playback-control' bash "$command"
