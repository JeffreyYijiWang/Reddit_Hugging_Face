"""Read-only checks on the isolated scan and its time-budget behavior."""
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT/'remaining_scan/code'))
import duckdb
from reddit_reid.common import BudgetStop, digest, load_config, load_json
from reddit_reid.keywords import VERSION
from reddit_reid.transport import Ledger

cfg = load_config(PROJECT/'config.remaining.yaml')
assert cfg['resources']['max_query_seconds'] is None
ledger = Ledger(cfg)
ledger.data['query_seconds'] = 10**12
ledger.check_time()
ledger.cfg = cfg | {'resources':cfg['resources'] | {'max_query_seconds':60}}
try:
    ledger.check_time()
except BudgetStop:
    pass
else:
    raise AssertionError('Finite budgets must still stop')
root = Path(cfg['data_root'])
baseline = load_json(root/'inputs/continuation_baseline.json')
queries = load_json(root/'inputs/keywords.json')
manifest = load_json(root/'inputs/source_manifest.json')
db = duckdb.connect(str(root/'state/research.duckdb'), read_only=True)
rows = db.execute('SELECT key,path,status,json FROM checkpoints').fetchall()
db.close()
imported = 0
for key,path,status,raw in rows:
    detail = json.loads(raw)
    if detail.get('imported_completion'):
        imported += 1
        assert status == 'complete'
        assert key == digest(dict(revision=manifest['revision'],path=path,stage='discovery',
                                  scope=cfg['discovery'],query_hash=digest(queries),
                                  matcher_version=VERSION,target_hash=None))
assert imported == baseline['completed_files']
assert baseline['completed_files'] + baseline['remaining_files'] == len(manifest['files'])
assert len(set(load_json(root/'inputs/prior_candidate_ids.json'))) == baseline['prior_candidates']
print(json.dumps({'unlimited_time_verified':True,'finite_budget_verified':True,
                  'reusable_completed_files':imported,'remaining_files':baseline['remaining_files'],
                  'earlier_candidate_ids_excluded':baseline['prior_candidates']}))
