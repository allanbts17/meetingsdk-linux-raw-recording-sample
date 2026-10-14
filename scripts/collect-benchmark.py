"""Run inside the agent container; emit only resource metrics and safe SDK fields."""
import argparse
import json
import re
import time
from pathlib import Path
from app.sdk_control import SdkControl


def resource_metrics():
    root = Path('/sys/fs/cgroup')
    cpu = dict(line.split() for line in (root / 'cpu.stat').read_text().splitlines())
    rss = 0
    for path in Path('/proc').glob('[0-9]*/status'):
        try:
            text = path.read_text()
            if re.search(r'^Name:\s+(meetingSDKDemo|ffmpeg)$', text, re.M):
                value = re.search(r'^VmRSS:\s+(\d+)', text, re.M)
                if value:
                    rss += int(value[1]) * 1024
        except (OSError, ProcessLookupError):
            pass
    return {'cpu_usec': int(cpu['usage_usec']),
            'throttled_usec': int(cpu.get('throttled_usec', 0)),
            'memory_bytes': int((root / 'memory.current').read_text()),
            'sdk_ffmpeg_rss_bytes': rss}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('bot_id')
    parser.add_argument('--seconds', type=int, default=660)
    args = parser.parse_args()
    directory = Path('/state/r') / args.bot_id
    sockets = list(directory.glob('*.sock'))
    if len(sockets) != 1:
        raise SystemExit('BENCHMARK_SOCKET_NOT_FOUND')
    control = SdkControl(str(sockets[0]), timeout=5)
    samples = []
    started = time.monotonic()
    previous = None
    while time.monotonic() - started < args.seconds:
        state = control.command('status')
        now = time.monotonic()
        item = dict(resource_metrics(), elapsed_seconds=now - started)
        item.update({k: state.get(k) for k in ('playback_id', 'playback_state',
                    'position_seconds', 'video_frames_sent', 'audio_blocks_sent',
                    'meeting_status', 'pause_reasons')})
        if previous:
            item['cpu_cores'] = ((item['cpu_usec'] - previous['cpu_usec']) / 1e6
                                 / (item['elapsed_seconds'] - previous['elapsed_seconds']))
        samples.append(item)
        previous = item
        if state.get('playback_state') in ('finished', 'failed', 'stopped'):
            break
        time.sleep(2)
    log = (directory / 'sdk.log').read_text(errors='replace')
    negotiated = re.findall(r'Video playback started: (\d+)x(\d+) at (\d+) fps', log)
    errors = [line for line in log.splitlines() if
              'frame send failed, SDK error:' in line or 'block send failed, SDK error:' in line]
    summary = {'samples': len(samples), 'elapsed_seconds': samples[-1]['elapsed_seconds'],
               'final_state': samples[-1]['playback_state'],
               'output': negotiated[-1] if negotiated else None,
               'cpu_cores_mean': ((samples[-1]['cpu_usec'] - samples[0]['cpu_usec']) / 1e6
                                  / max(samples[-1]['elapsed_seconds'], .001)),
               'cpu_cores_peak': max(s.get('cpu_cores', 0) for s in samples),
               'memory_peak_bytes': max(s['memory_bytes'] for s in samples),
               'sdk_ffmpeg_rss_peak_bytes': max(s['sdk_ffmpeg_rss_bytes'] for s in samples),
               'sdk_send_error_messages': len(errors),
               'final_video_frames_sent': samples[-1]['video_frames_sent'],
               'final_audio_blocks_sent': samples[-1]['audio_blocks_sent']}
    if negotiated and samples[-1]['position_seconds'] is not None:
        expected = round(float(negotiated[-1][2]) * samples[-1]['position_seconds'])
        summary['frames_not_accepted_estimate'] = max(0, expected - samples[-1]['video_frames_sent'])
    print(json.dumps({'summary': summary, 'samples': samples}))


if __name__ == '__main__':
    main()
