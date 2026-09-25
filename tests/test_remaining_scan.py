import json
import importlib.util
from pathlib import Path

from reddit_reid.common import digest
from reddit_reid.keywords import VERSION

spec = importlib.util.spec_from_file_location('prepare_remaining', Path(__file__).resolve().parents[1]/'tools/prepare_remaining_scan.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_completion_reuse_requires_matching_revision_queries_and_whole_file():
    queries = [{'query_id':'synthetic', 'normalized':'found my post'}]
    manifest = [{'path':'synthetic.parquet','revision':'fixed'}]
    scope = {'start_month':'2010-01','subreddits':[]}
    identity = dict(revision='fixed', path='synthetic.parquet', stage='discovery', scope=scope,
                    query_hash=digest(queries), matcher_version=VERSION, target_hash=None)
    row = [digest(identity),'discovery','synthetic.parquet','complete',100,json.dumps({'scope':scope})]
    result = module.compatible_completed([row],manifest,queries,{'subreddits':[]})
    assert result['synthetic.parquet']['scanned'] == 100
    assert result['synthetic.parquet']['detail']['imported_completion']['source_key'] == row[0]
    assert not module.compatible_completed([row],manifest,queries+[{'different':True}],{})
    assert not module.compatible_completed([row],[{'path':'synthetic.parquet','revision':'other'}],queries,{})
    assert not module.compatible_completed([row[:3]+['partial']+row[4:]],manifest,queries,{})
    filtered = {'subreddits':['subset']}
    row[0] = digest(identity | {'scope':filtered})
    row[5] = json.dumps({'scope':filtered})
    assert not module.compatible_completed([row],manifest,queries,{})
