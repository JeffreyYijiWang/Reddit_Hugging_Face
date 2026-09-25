"""Prepare an isolated, reproducible continuation without modifying the first run."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import duckdb
import yaml

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from reddit_reid.common import digest, dumps, now, save_json
from reddit_reid.keywords import VERSION


def compatible_completed(rows, manifest, queries, scope):
    """Reuse only proven whole-file discovery with this revision/query/matcher."""
    by_path = {f['path']: f for f in manifest}
    query_hash = digest(queries)
    result = {}
    for key, stage, path, status, scanned, raw in rows:
        c = json.loads(raw)
        if stage != 'discovery' or status != 'complete' or path not in by_path:
            continue
        old_scope = c.get('scope', {})
        if old_scope.get('subreddits') or c.get('target_hash'):
            continue
        identity = dict(revision=by_path[path]['revision'], path=path,
                        stage='discovery', scope=old_scope, query_hash=query_hash,
                        matcher_version=VERSION, target_hash=None)
        if digest(identity) != key:
            continue
        if path in result and result[path]['scanned'] >= scanned:
            continue
        new_key = digest(identity | {'scope': scope})
        detail = c | {'key': new_key, 'stage': 'discovery', 'scope': scope,
                      'status': 'complete', 'rows_returned': scanned,
                      'imported_completion': {'source_key': key, 'source_scope': old_scope,
                                              'source_database': 'data/state/research.duckdb'}}
        result[path] = dict(key=new_key, scanned=scanned, detail=detail)
    return result


def replace_once(path, before, after):
    text = path.read_text(encoding='utf-8')
    if text.count(before) != 1:
        raise ValueError(f'Expected one patch location in {path.name}: {before[:80]}')
    path.write_text(text.replace(before, after), encoding='utf-8')


def prepare():
    run = PROJECT / 'remaining_scan'
    data = PROJECT / 'data_remaining'
    config_path = PROJECT / 'config.remaining.yaml'
    if run.exists() or data.exists() or config_path.exists():
        raise RuntimeError('Continuation already exists; resume it instead of resetting its baseline.')
    cfg = yaml.safe_load((PROJECT/'config.yaml').read_text(encoding='utf-8'))
    source = PROJECT / cfg['data_root']
    manifest = json.loads((source/'inputs/source_manifest.json').read_text(encoding='utf-8'))
    queries = json.loads((source/'inputs/keywords.json').read_text(encoding='utf-8'))
    # One read-only transaction fixes the original-run boundary before any new scan.
    db = duckdb.connect(str(source/'state/research.duckdb'), read_only=True)
    try:
        db.execute('BEGIN TRANSACTION')
        rows = db.execute('SELECT key,stage,path,status,scanned,json FROM checkpoints').fetchall()
        prior_ids = [r[0] for r in db.execute('SELECT DISTINCT typed_id FROM hits ORDER BY typed_id').fetchall()]
        db.execute('COMMIT')
    finally:
        db.close()
    completed = compatible_completed(rows, manifest['files'], queries, cfg['discovery'])
    if not completed:
        raise RuntimeError('No compatible completed checkpoints; refusing to rescan the archive blindly.')
    (run/'code/tools').mkdir(parents=True)
    shutil.copytree(PROJECT/'reddit_reid', run/'code/reddit_reid', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(PROJECT/'tools/export-workbook.mjs', run/'code/tools/export-workbook.mjs')
    shutil.copy2(PROJECT/'tools/remaining_runner.py', run/'code/reddit_reid/remaining.py')
    original_hashes = {str(p.relative_to(run/'code')): digest(p.read_bytes())
                       for p in (run/'code').rglob('*') if p.is_file()}
    for folder in ('inputs', 'state', 'inspection', 'cache', 'tmp', 'logs', 'cases',
                   'annotations', 'exports', 'records/submissions', 'records/comments'):
        (data/folder).mkdir(parents=True, exist_ok=True)
    for name in ('source_manifest.json', 'keywords.json', 'keyword_audit.json', 'codebook.md'):
        shutil.copy2(source/'inputs'/name, data/'inputs'/name)
    for name in ('inventory_summary.json', 'samples.json', 'join_demonstration.json'):
        if (source/'inspection'/name).exists():
            shutil.copy2(source/'inspection'/name, data/'inspection'/name)
    shutil.copytree(source/'cache/extensions', data/'cache/extensions')
    save_json(data/'inputs/prior_candidate_ids.json', prior_ids)
    cfg['data_root'] = 'data_remaining'
    cfg['resources'].update(max_query_seconds=None, workers=2, threads=1,
                            memory_limit='512MB', worker_memory_limit='384MB', batch_size=4096)
    cfg['model'].update(endpoint=None, name=None)
    cfg['workflow'].update(collect_comments=False, retry_failed_passes=2)
    cfg['export'].update(workbook_stem='review_remaining',
                         output_directory=str(PROJECT/'outputs/01a0d7fb-20a1-75c2-83ec-202ecae1a0ed'))
    config_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding='utf-8')
    code = run/'code/reddit_reid'
    replace_once(code/'transport.py',
                 'if self.data["query_seconds"] >= self.cfg["resources"]["max_query_seconds"]:',
                 'if self.cfg["resources"]["max_query_seconds"] is not None and self.data["query_seconds"] >= self.cfg["resources"]["max_query_seconds"]:')
    replace_once(code/'parallel.py', 'import json\n', 'import json\nimport math\n')
    replace_once(code/'parallel.py', '_cancel = None\n', '_cancel = None\n_prior_ids = set()\n')
    replace_once(code/'parallel.py', 'global _matcher, _queue, _cfg, _cancel', 'global _matcher, _queue, _cfg, _cancel, _prior_ids')
    replace_once(code/'parallel.py',
                 '_matcher, _queue, _cfg, _cancel = Matcher(queries), messages, cfg, cancel',
                 "_matcher, _queue, _cfg, _cancel = Matcher(queries), messages, cfg, cancel\n    _prior_ids = set(load_json(Path(cfg['data_root'])/'inputs/prior_candidate_ids.json', []))")
    replace_once(code/'parallel.py', "'file_bytes':file['bytes'],'started':now()", "'previously_saved_matches':0,'file_bytes':file['bytes'],'started':now()")
    replace_once(code/'parallel.py',
                 'timer = threading.Timer(max(.01, job[\'deadline\']-time.monotonic()),db.interrupt)\n    timer.daemon = True\n    timer.start()',
                 "timer = None\n    if math.isfinite(job['deadline']):\n        timer = threading.Timer(max(.01, job['deadline']-time.monotonic()),db.interrupt)\n        timer.daemon = True\n        timer.start()")
    replace_once(code/'parallel.py', 'timer.cancel(); db.close()', 'if timer is not None:\n            timer.cancel()\n        db.close()')
    replace_once(code/'parallel.py', 'record = canonical(row,file)\n                    if not found:',
                 "record = canonical(row,file)\n                    if found and record['typed_id'] in _prior_ids:\n                        result['previously_saved_matches'] += 1\n                        continue\n                    if not found:")
    replace_once(code/'parallel.py', 'def scan_parallel(cfg):', 'def scan_parallel(cfg, max_files=None):')
    replace_once(code/'parallel.py', "deadline = start + cfg['resources']['max_query_seconds'] - ledger.data['query_seconds']",
                 "limit = cfg['resources']['max_query_seconds']\n    deadline = float('inf') if limit is None else start + limit - ledger.data['query_seconds']")
    replace_once(code/'parallel.py', "    report = {'run_id':run_id", "    snapshot_limited = max_files is not None and len(pending) > max_files\n    if max_files is not None:\n        pending = pending[:max_files]\n    report = {'run_id':run_id")
    replace_once(code/'parallel.py', "stopped = 'seven_hour_query_ceiling'", "stopped = 'query_time_ceiling'")
    replace_once(code/'parallel.py', "else 'failed_files_remain')", "else 'snapshot_limit' if snapshot_limited else 'failed_files_remain')")
    # Preserve the established review columns and formatting in a separate output.
    replace_once(code/'export.py', 'out = root / "exports"', "out = Path(cfg['export'].get('output_directory', root / 'exports'))")
    replace_once(code/'export.py', "stem = 'research_review' if part_number == 1 else f'research_review_{part_number:03d}'",
                 "base_stem = cfg['export'].get('workbook_stem', 'research_review')\n            stem = base_stem if part_number == 1 else f'{base_stem}_{part_number:03d}'")
    replace_once(code/'export.py', 'str(out / "research_review.xlsx")', "str(out / (cfg['export'].get('workbook_stem', 'research_review') + '.xlsx'))")
    replace_once(code/'export.py', '    full_parts = []',
                 "    baseline = load_json(root/'inputs/continuation_baseline.json', {})\n    new_complete = [c for c in checkpoints if c.get('stage') == 'discovery' and c.get('status') == 'complete' and not c.get('imported_completion')]\n    extra_summary = {\n        'Run': 'Remaining archive files; original review is preserved separately',\n        'Time limit': 'None',\n        'Files completed before continuation': baseline.get('completed_files', 0),\n        'Files left at continuation start': baseline.get('remaining_files', 0),\n        'Newly completed files': len(new_complete),\n        'New records in completed files': sum(c['scanned'] for c in new_complete),\n        'Files still unfinished': baseline.get('remaining_files', 0)-len(new_complete),\n        'Earlier candidate IDs excluded': baseline.get('prior_candidates', 0),\n        'Coverage interpretation': 'Imported completed files contribute coverage only. Review rows contain newly retained candidates.',\n    }\n    summary.update(extra_summary)\n    tables['Summary']['rows'] += list(map(list, extra_summary.items()))\n    full_parts = []")
    # Reuse report generation while explicitly handling the unlimited budget.
    replace_once(code/'report.py', "{cfg['resources']['max_query_seconds']/3600:.1f} hours", "{'none' if cfg['resources']['max_query_seconds'] is None else str(cfg['resources']['max_query_seconds']/3600) + ' hours'}")
    sys.path.insert(0, str(run/'code'))
    # Store schema is unchanged; this creates only the isolated continuation DB.
    from reddit_reid.store import Store
    local_cfg = cfg | {'data_root': str(data)}
    store = Store(local_cfg, remote=False)
    store.db.execute('BEGIN TRANSACTION')
    for path, c in completed.items():
        store.checkpoint(c['key'], 'discovery', path, 'complete', c['scanned'], c['detail'])
    store.db.execute('COMMIT')
    store.close()
    baseline = dict(created_at=now(), repo=manifest['repo'], revision=manifest['revision'],
                    query_hash=digest(queries), matcher_version=VERSION,
                    selected_files=len(manifest['files']), completed_files=len(completed),
                    completed_records=sum(c['scanned'] for c in completed.values()),
                    remaining_files=len(manifest['files'])-len(completed),
                    prior_candidates=len(prior_ids), source_code_hashes=original_hashes,
                    completed_paths=sorted(completed),
                    note='Original database read-only. Imported completions verified by original checkpoint hashes. Earlier candidate IDs are excluded from the new collection.')
    save_json(data/'inputs/continuation_baseline.json', baseline)
    print(dumps({k:v for k,v in baseline.items() if k not in ('completed_paths','source_code_hashes')}))


if __name__ == '__main__':
    prepare()
