"""Copied into the frozen continuation package by prepare_remaining_scan.py."""
from __future__ import annotations

import argparse
from concurrent.futures.process import BrokenProcessPool
import os
import sys
import time
import traceback
from pathlib import Path

import duckdb

from .common import dumps, load_config, load_json, now, save_json
from .fullrun import finalize
from .memory_guard import allocation_headroom
from .parallel import scan_parallel


def wait_for_memory(cfg, status, status_path):
    minimum = cfg['resources'].get('minimum_query_memory_bytes', 0)
    while minimum:
        available = allocation_headroom()
        if available >= minimum or (Path(cfg['data_root'])/'state/stop_requested').exists():
            break
        status.update(state='waiting_for_memory', available_allocation_bytes=available,
                      minimum_allocation_bytes=minimum, memory_checked_at=now())
        save_json(status_path, status)
        time.sleep(10)
    status['state'] = 'running'
    save_json(status_path, status)


def scan_with_recovery(cfg, smoke_files, status, status_path):
    """Bound worker/allocator retries; preserve checkpoints and the same ledger."""
    maximum = cfg['workflow'].get('automatic_full_run_restart_attempts', 2)
    while True:
        wait_for_memory(cfg, status, status_path)
        try:
            return scan_parallel(cfg, max_files=smoke_files)
        except (BrokenProcessPool, duckdb.OutOfMemoryException) as exc:
            used = status.get('automatic_restarts', 0)
            status.setdefault('recoverable_failures', []).append({
                'at': now(), 'error': type(exc).__name__ + ': ' + str(exc),
                'restart_available': used < maximum})
            if used >= maximum:
                save_json(status_path, status)
                raise
            status.update(state='recovering_scan', automatic_restarts=used+1)
            save_json(status_path, status)
            print(dumps({'recovering_scan': type(exc).__name__, 'restart': used+1,
                         'maximum_restarts': maximum, 'checkpoint_resume': True}), flush=True)
            time.sleep(10)
            status['state'] = 'running'
            save_json(status_path, status)


def run(cfg, smoke_files=None):
    root = Path(cfg['data_root'])
    status_path = root/'state/full_run_status.json'
    lock_path = root/'state/runner.lock'
    import psutil
    previous = load_json(lock_path, {})
    if previous.get('pid') and psutil.pid_exists(previous['pid']):
        process = psutil.Process(previous['pid'])
        if abs(process.create_time()-previous.get('process_created', 0)) < 1:
            raise RuntimeError('This continuation already has a live runner.')
    save_json(lock_path, {'pid':os.getpid(), 'process_created':psutil.Process().create_time()})
    baseline = load_json(root/'inputs/continuation_baseline.json')
    status = dict(pid=os.getpid(), started_at=now(), state='running', query_limit_seconds=None,
                  config_path=cfg['config_path'], checkpoint_resume=True,
                  scope='All remaining pinned archive files, submissions then comments',
                  baseline_complete_files=baseline['completed_files'],
                  files_remaining_at_start=baseline['remaining_files'],
                  export_directory=cfg['export']['output_directory'],
                  smoke_files=smoke_files)
    save_json(status_path, status)
    try:
        attempts = 1 if smoke_files else 1 + cfg['workflow'].get('retry_failed_passes', 2)
        for attempt in range(attempts):
            status.update(state='running', attempt=attempt+1)
            save_json(status_path, status)
            result = scan_with_recovery(cfg, smoke_files, status, status_path)
            status.update(discovery_complete=result['complete'], stop_reason=result['stop_reason'],
                          state='exporting', scan_finished_at=now())
            save_json(status_path, status)
            status['results'] = finalize(cfg)
            save_json(status_path, status)
            if result['complete'] or result['stop_reason'] != 'failed_files_remain' or attempt == attempts-1:
                break
            print(dumps({'retry_failed_files':True,'attempt':attempt+2}), flush=True)
            time.sleep(10)
        status['state'] = 'complete' if result['complete'] else 'snapshot_ready' if smoke_files else 'stopped_with_partial_coverage'
    except BaseException as exc:
        status.update(state='failed_or_interrupted', error=type(exc).__name__+': '+str(exc))
        traceback.print_exc()
        # Canonical matches and checkpoints remain resumable even if export fails.
        raise
    finally:
        status['finished_at'] = now()
        save_json(status_path, status)
        if lock_path.exists() and load_json(lock_path,{}).get('pid') == os.getpid():
            lock_path.unlink()
    print(dumps(status), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--smoke-files', type=int)
    args = parser.parse_args()
    cfg = load_config(args.config)
    if cfg['resources']['max_query_seconds'] is not None or cfg['resources']['workers'] < 1:
        raise ValueError('Continuation requires an unlimited time budget and at least one reader.')
    run(cfg, args.smoke_files)
