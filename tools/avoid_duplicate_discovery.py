"""Let the current context query finish, then skip this run's duplicate discovery.

The separately authorized continuation uses data_remaining. This helper touches
only the original run's state files; ChatGPT review has its own stop marker.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def decision(supervisor, context, expected_pid, expected_start):
    if supervisor.get('pid') != expected_pid:
        return 'different_supervisor'
    if supervisor.get('state') in ('failed_or_interrupted', 'finished_with_reported_coverage'):
        return 'supervisor_ended'
    if context.get('started_at') != expected_start:
        return 'different_context_run'
    if context.get('active') is False and context.get('finished_at'):
        return 'skip_duplicate_discovery'
    return 'waiting_for_context'


def run(expected_pid, expected_start, max_seconds=4200):
    state = Path(__file__).resolve().parents[1] / 'data' / 'state'
    report_path = state / 'discovery_coordination.json'
    report = {
        'supervisor_pid': expected_pid,
        'context_started_at': expected_start,
        'reason': 'Remaining archive discovery is handled by the separate data_remaining continuation.',
        'state': 'waiting_for_context',
    }

    def save():
        report['updated_at'] = datetime.now(timezone.utc).isoformat()
        temporary = report_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, indent=2), encoding='utf-8')
        temporary.replace(report_path)

    save()
    deadline = time.monotonic() + max_seconds
    while time.monotonic() < deadline:
        try:
            action = decision(read_json(state / 'resumed_research_status.json'),
                              read_json(state / 'review_context.json'), expected_pid, expected_start)
        except (OSError, ValueError):
            time.sleep(2)
            continue
        if action == 'skip_duplicate_discovery':
            marker = state / 'stop_requested'
            try:
                with marker.open('x', encoding='utf-8') as stream:
                    stream.write(report['reason'] + '\nContext collection has finished. ChatGPT review continues.\n')
                report['marker_created'] = True
            except FileExistsError:
                report['marker_created'] = False
            report['state'] = action
            save()
            return report
        if action != 'waiting_for_context':
            report['state'] = action
            save()
            return report
        time.sleep(2)
    report['state'] = 'timed_out_without_changes'
    save()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--supervisor-pid', type=int, required=True)
    parser.add_argument('--context-started-at', required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.supervisor_pid, args.context_started_at)))
