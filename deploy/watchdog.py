"""Host health watchdog for the one managed container; systemd performs safe restart."""
import json
import subprocess


def main():
    result = subprocess.run(["docker", "inspect", "zoom-bot-agent"], capture_output=True, text=True)
    if result.returncode:
        return 0
    try:
        container = json.loads(result.stdout)[0]
        if (container["Config"].get("Labels") or {}).get("com.zoom-bot.managed") != "true":
            return 1
        state = container["State"]
        if state.get("Running") and state.get("Health", {}).get("Status") == "unhealthy":
            print('MANAGED_AGENT_UNHEALTHY_RESTART_REQUESTED')
            return subprocess.run(["systemctl", "restart", "zoom-bot-agent.service"], timeout=120).returncode
        return 0
    except Exception:
        print('MANAGED_AGENT_WATCHDOG_FAILED')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
