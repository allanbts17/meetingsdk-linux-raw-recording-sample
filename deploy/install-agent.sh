#!/bin/bash
set -euo pipefail
test "$(id -u)" = 0
stage=$(readlink -f "${1:?staging directory required}")
test "$(dirname "$stage")" = /tmp
[[ "$(basename "$stage")" =~ ^zoom-bot-deploy-[0-9a-f]{7,40}$ ]]
if systemctl is-active --quiet zoom-bot-agent.service; then
    echo ACTIVE_AGENT_REQUIRES_EXPLICIT_STOP
    exit 1
fi
install -d -m 0755 /opt/zoom-bot/bin
install -d -m 0700 /etc/zoom-bot /var/lib/zoom-bot /var/lib/zoom-bot/media
for file in host_reconcile.py pull_image.py watchdog.py; do
    install -m 0644 "$stage/$file" "/opt/zoom-bot/bin/$file"
done
install -m 0755 "$stage/run-agent.sh" /opt/zoom-bot/bin/run-agent.sh
install -m 0600 "$stage/agent.env.example" /etc/zoom-bot/agent.env
install -m 0600 "$stage/image.env" /etc/zoom-bot/image.env
for file in zoom-bot-agent.service zoom-bot-watchdog.service zoom-bot-watchdog.timer; do
    install -m 0644 "$stage/$file" "/etc/systemd/system/$file"
done
systemctl daemon-reload
systemctl enable --now zoom-bot-agent.service zoom-bot-watchdog.timer
echo MANAGED_AGENT_INSTALLED
