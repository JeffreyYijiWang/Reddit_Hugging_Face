"""Bounded actual-source smoke test of four independent readers and one writer."""
from pathlib import Path
from reddit_reid.common import load_config, load_json, save_json
from reddit_reid.parallel import scan_parallel

if __name__ == '__main__':
    cfg = load_config('config.yaml')
    root = Path(cfg['data_root'])
    files = load_json(root/'inputs/source_manifest.json')['files']
    cfg['discovery'] = {'start_month':None,'end_month':None,'subreddits':[], 'kinds':['submissions','comments'],
        'selected_paths':list(reversed([f['path'] for f in files if f['month'] in ['2005-12','2006-01']]))}
    used = load_json(root/'state/resource_ledger.json')['query_seconds']
    cfg['resources']['max_query_seconds'] = min(25200,used+45)
    result = scan_parallel(cfg)
    save_json(root/'inspection/parallel_smoke.json',result)
    assert result['complete'], result.get('stop_reason')
    print({'parallel_smoke_complete':result['complete'],'files':len(result['files']),'seconds':result['elapsed_seconds']})
