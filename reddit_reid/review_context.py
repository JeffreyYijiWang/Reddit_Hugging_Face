"""Batch collection of containing posts and archived comments within one ledger."""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .common import BudgetStop, digest, load_json, now, save_json
from .scanner import scan
from .store import Store


def collect(cfg, max_seconds=3600):
    root = Path(cfg['data_root'])
    manifest = load_json(root/'inputs/source_manifest.json')['files']
    last_comment_month = max(f['month'] for f in manifest if f['kind']=='comments')
    store = Store(cfg,remote=False)
    records = {r['typed_id']:r for r in store.records()}
    hits = store.hits()
    store.close()
    seeds = [records[rid] for rid in {h['typed_id'] for h in hits}]
    eligible = [r for r in seeds if datetime.fromtimestamp(r.get('created_utc') or 0,timezone.utc).strftime('%Y-%m') <= last_comment_month]
    targets = sorted({r['thread_id'] for r in eligible if r.get('thread_id')})
    status = {'active':True,'started_at':now(),'archive_last_comment_month':last_comment_month,
        'eligible_threads':len(targets),'out_of_comment_archive_seed_records':len(seeds)-len(eligible),
        'threads':{},'maximum_this_run_seconds':max_seconds,
        'public_reddit_access':'One logged public JSON probe returned HTTP 403; live comments not collected'}
    path = root/'state/review_context.json'
    save_json(path,status)
    if not targets:
        status.update(active=False,finished_at=now()); save_json(path,status); return status
    start = time.monotonic()
    # Comment creation is an upper bound on creation of its containing post.
    latest_seed_month = max(datetime.fromtimestamp(r.get('created_utc') or 0,timezone.utc).strftime('%Y-%m') for r in eligible)
    missing_posts = [tid for tid in targets if tid not in records]
    try:
        if missing_posts:
            files = [f for f in manifest if f['kind']=='submissions' and f['month']<=latest_seed_month]
            result = scan(cfg,stage='context',targets=missing_posts,files=files,resume=True,
                max_seconds=max(1,max_seconds-(time.monotonic()-start)),continue_on_error=True)
            status['containing_posts_query'] = {'run_id':result['run_id'],'complete':result['complete'],'files':len(files)}
            save_json(path,status)
        store = Store(cfg,remote=False)
        records = {r['typed_id']:r for r in store.records()}
        store.close()
        # Include all historical partitions if any original remains unresolved.
        earliest = min(datetime.fromtimestamp(records[t]['created_utc'],timezone.utc).strftime('%Y-%m') for t in targets) if all(t in records and records[t].get('created_utc') for t in targets) else min(f['month'] for f in manifest if f['kind']=='comments')
        files = [f for f in manifest if f['kind']=='comments' and f['month']>=earliest]
        if time.monotonic()-start >= max_seconds:
            raise BudgetStop('Context collection run allowance reached; cumulative ledger retained')
        result = scan(cfg,stage='context',targets=targets,files=files,resume=True,
            max_seconds=max(1,max_seconds-(time.monotonic()-start)),continue_on_error=True)
        status['comments_query'] = {'run_id':result['run_id'],'complete':result['complete'],
            'first_month':earliest,'last_month':last_comment_month,'selected_files':len(files),
            'target_set_hash':digest(targets)}
        status['threads'] = {tid:{'comments_query_complete':bool(result['complete']),
            'run_id':result['run_id'],'first_month':earliest,'last_month':last_comment_month,
            'containing_post_retrieved':tid in records,'target_set_hash':digest(targets)} for tid in targets}
    except BudgetStop as exc:
        status['stop_reason'] = str(exc)
    finally:
        status.update(active=False,finished_at=now(),elapsed_seconds=time.monotonic()-start)
        save_json(path,status)
    return status
