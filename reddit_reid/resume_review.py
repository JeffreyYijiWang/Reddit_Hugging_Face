"""One database writer; discovery and classifier checkpoints survive interruption."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .common import load_config, load_json, now, save_json
from .fullrun import finalize, post_bundles
from .parallel import scan_parallel
from .review_context import collect


def run(config='config.yaml'):
    cfg = load_config(config)
    root = Path(cfg['data_root'])
    ledger = load_json(root/'state/resource_ledger.json')
    remaining = max(0,cfg['resources']['max_query_seconds']-ledger['query_seconds'])
    status_path = root/'state/resumed_research_status.json'
    status = {'pid':os.getpid(),'state':'collecting_archived_context','started_at':now(),
        'query_seconds_already_used':ledger['query_seconds'],'query_seconds_remaining_at_start':remaining,
        'query_limit_seconds':cfg['resources']['max_query_seconds'],'original_budget_preserved':True}
    save_json(status_path,status)
    model = None
    stdout = stderr = None
    try:
        status['context'] = collect(cfg,max_seconds=min(3600,remaining))
        status['bundles_before_discovery'] = post_bundles(cfg)
        remaining = max(0,cfg['resources']['max_query_seconds']-load_json(root/'state/resource_ledger.json')['query_seconds'])
        qualification = load_json(root/'inputs/chatgpt_qualification.json', {})
        if qualification.get('accepted_for_model_generated_review') and remaining>0:
            # The model process writes validated per-case files only, never DuckDB.
            stdout = (root/'logs/chatgpt-bulk-console.txt').open('w',encoding='utf-8')
            stderr = (root/'logs/chatgpt-bulk-errors.txt').open('w',encoding='utf-8')
            model = subprocess.Popen([sys.executable,'-u','-m','reddit_reid.chatgpt_review','--batch-size','8',
                '--max-seconds',str(max(1,int(remaining)))],cwd=root.parent,stdout=stdout,stderr=stderr,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            status.update(state='discovering_and_reviewing',model_process_id=model.pid)
        else:
            status.update(state='discovering',model_review='Withheld: qualification unavailable/failed or no remaining run allowance')
        save_json(status_path,status)
        if remaining>0:
            status['discovery'] = scan_parallel(cfg)
        status.update(state='waiting_for_current_model_batch')
        save_json(status_path,status)
        if model:
            model.wait()
            status['model_returncode'] = model.returncode
        status.update(state='exporting_available_results')
        save_json(status_path,status)
        status['results'] = finalize(cfg)
        status['state'] = 'finished_with_reported_coverage'
    except BaseException as exc:
        status.update(state='failed_or_interrupted',error=type(exc).__name__+': '+str(exc))
        # Do not launch another writer or replace a usable export on failure.
        raise
    finally:
        if stdout: stdout.close()
        if stderr: stderr.close()
        status['finished_at'] = now()
        save_json(status_path,status)
    return status


if __name__=='__main__':
    print(json.dumps(run(sys.argv[1] if len(sys.argv)>1 else 'config.yaml')))
