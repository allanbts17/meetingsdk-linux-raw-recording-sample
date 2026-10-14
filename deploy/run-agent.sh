#!/bin/bash
set -euo pipefail
name=zoom-bot-agent
root=/var/lib/zoom-bot
if [ "${1:-}" = stop ]; then
    if docker inspect "$name" >/dev/null 2>&1; then
        test "$(docker inspect --format '{{index .Config.Labels "com.zoom-bot.managed"}}' "$name")" = true
        docker stop --time 80 "$name"
    fi
    exit 0
fi
source /etc/zoom-bot/image.env
python3 /opt/zoom-bot/bin/pull_image.py "$ZOOM_AGENT_IMAGE"
python3 /opt/zoom-bot/bin/host_reconcile.py --state-root "$root"
if docker inspect "$name" >/dev/null 2>&1; then
    test "$(docker inspect --format '{{index .Config.Labels "com.zoom-bot.managed"}}' "$name")" = true
    test "$(docker inspect --format '{{.State.Running}}' "$name")" = false
    test "$(docker inspect --format '{{.State.Pid}}' "$name")" = 0
    docker rm "$name"
fi
docker create --name "$name" --label com.zoom-bot.managed=true --stop-timeout 80 \
    --memory 6g --cpus 2 --shm-size 256m --log-driver local --log-opt max-size=10m --log-opt max-file=3 \
    --env-file /etc/zoom-bot/agent.env \
    --mount "type=bind,source=$root,target=/state" \
    --mount "type=bind,source=$root/media,target=/sdk-media,readonly" \
    --publish 10.128.0.2:8080:8080 --publish 127.0.0.1:8080:8080 "$ZOOM_AGENT_IMAGE"
exec docker start --attach "$name"
