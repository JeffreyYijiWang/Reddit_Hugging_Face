"""Bounded process readers + one coordinator/writer, with durable handoff files."""
from __future__ import annotations

import concurrent.futures
import json
import multiprocessing
import os
import queue
import threading
import time
from pathlib import Path

import duckdb
import psutil

from .common import BudgetStop, check_disk, digest, disk_usage, dumps, load_json, now, save_json
from .inspection import describe
from .keywords import Matcher, VERSION
from .scanner import canonical, select_files, triage_flags, COLUMNS
from .store import Store
from .transport import Ledger, Relay

_matcher = None
_queue = None
_cfg = None
_cancel = None


def _initialize(queries, messages, cfg, cancel):
    global _matcher, _queue, _cfg, _cancel
    _matcher, _queue, _cfg, _cancel = Matcher(queries), messages, cfg, cancel


def _read_file(job):
    """No access to research.duckdb. Distinct immutable result files only."""
    file, key = job['file'], job['key']
    root = Path(_cfg['data_root'])
    resources = _cfg['resources']
    started = time.monotonic()
    result = {'path':file['path'],'key':key,'kind':file['kind'],'stage':'discovery', 'status':'partial',
        'rows_returned':0,'matched_records':0,'phrase_hits':0,'matching_seconds':0.0,'peak_rss_bytes':0,
        'file_bytes':file['bytes'],'started':now(),'worker_pid':os.getpid(),'scope':_cfg['discovery'],
        'target_hash':None,'query_set_hash':job['query_hash'],'matcher_version':VERSION,
        'restart_policy':'Restart incomplete file and deduplicate; durable handoff files recover first'}
    db = duckdb.connect(':memory:')
    temp_dir = root/'tmp'/f'spill-{os.getpid()}'
    temp_dir.mkdir(exist_ok=True)
    db.execute('SET threads = 1')
    db.execute('SET memory_limit = ?', [resources.get('worker_memory_limit','512MB')])
    db.execute('SET temp_directory = ?', [str(temp_dir)])
    db.execute('SET max_temp_directory_size = ?', [str(resources['spill_bytes']//resources.get('workers',4))+'B'])
    db.execute('SET extension_directory = ?', [str(root/'cache/extensions')])
    db.execute('LOAD httpfs')
    db.execute('SET http_timeout = 60')
    db.execute('SET http_retries = 1')
    db.execute('SET enable_progress_bar = false')
    timer = threading.Timer(max(.01, job['deadline']-time.monotonic()),db.interrupt)
    timer.daemon = True
    timer.start()
    negative = []
    last_progress = 0
    try:
        schema = file.get('schema') or describe(db,job['url'])
        columns = [c for c in COLUMNS if c in {v['name'] for v in schema}]
        result['source_row_count'] = file.get('row_count') or db.execute('SELECT count(*) FROM read_parquet(?)',[job['url']]).fetchone()[0]
        sql = 'SELECT ' + ','.join('"'+c+'"' for c in columns) + ' FROM read_parquet(?)'
        params = [job['url']]
        filters = []
        text_fields = ('title','selftext') if file['kind']=='submissions' else ('body',)
        pattern = _matcher.coarse_pattern()
        if pattern:
            filters.append('(' + ' OR '.join('regexp_matches(coalesce("'+field+'",\'\'), ?, \'i\')' for field in text_fields) + ')')
            params.extend([pattern]*len(text_fields))
            result['prefilter'] = 'Native required-word regex with exhaustive NFKC/casefold ASCII-compatibility escape hatch; exact Aho-Corasick verification follows'
        if _cfg['discovery'].get('subreddits'):
            filters.append('lower(subreddit) IN (SELECT unnest(?))')
            params.append([s.lower() for s in _cfg['discovery']['subreddits']])
        if filters:
            sql += ' WHERE ' + ' AND '.join(filters)
        result['sql'] = sql
        result['prefilter_hash'] = digest(pattern)
        result['subreddits'] = _cfg['discovery'].get('subreddits',[])
        for batch in db.execute(sql,params).fetch_record_batch(resources['batch_size']):
            if _cancel.is_set() or time.monotonic() >= job['deadline'] or (root/'state/stop_requested').exists():
                raise BudgetStop('deadline_or_requested_stop')
            texts = {field:batch.column(field).to_pylist() for field in text_fields}
            records, hits = [], []
            match_start = time.perf_counter()
            for index in range(batch.num_rows):
                found = []
                for field in text_fields:
                    for hit in _matcher.find(texts[field][index] or ''):
                        hit['field'] = field
                        found.append(hit)
                if found or len(negative) < 2:
                    row = {name:batch.column(name)[index].as_py() for name in batch.schema.names}
                    record = canonical(row,file)
                    if not found:
                        record['sampling_basis'] = 'First two nonmatching records per selected shard; convenience sample only'
                        negative.append(record)
                        continue
                    record['triage_flags'] = triage_flags('\n'.join(row.get(f) or '' for f in text_fields))
                    records.append(record)
                    result['matched_records'] += 1
                    result['phrase_hits'] += len(found)
                    for hit in found:
                        hit.update(typed_id=record['typed_id'],thread_id=record['thread_id'],query_set_hash=job['query_hash'],source=record['source'],run_id=job['run_id'])
                        hit['hit_id'] = digest([record['typed_id'],hit['query_id'],hit['field'],hit['start'],hit['end'],file['revision']])
                        hits.append(hit)
            result['matching_seconds'] += time.perf_counter()-match_start
            result['rows_returned'] += batch.num_rows
            result['peak_rss_bytes'] = max(result['peak_rss_bytes'],psutil.Process().memory_info().rss)
            result['elapsed_seconds'] = time.monotonic()-started
            if records:
                # Raw records/hits are durable before the writer advances coverage.
                path = root/'tmp/worker_results'/f"{key}-{result['rows_returned']}.json"
                save_json(path, {'records':records,'hits':hits,'checkpoint':dict(result)})
                _queue.put({'type':'batch','path':str(path)}, timeout=120)
            elif result['rows_returned']-last_progress >= 131072:
                _queue.put({'type':'progress','checkpoint':dict(result)}, timeout=120)
                last_progress = result['rows_returned']
        result['status'] = 'complete'
        result['prefilter_rows_returned'] = result['rows_returned']
        if not _cfg['discovery'].get('subreddits'):
            result['rows_returned'] = result['source_row_count']
            result['record_count_basis'] = 'Metadata row count after complete native prefilter scan; Python exact matcher sees only possible matches'
    except Exception as exc:
        result['status'] = 'partial' if result['rows_returned'] else 'failed'
        result['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        timer.cancel(); db.close()
        result['elapsed_seconds'] = time.monotonic()-started
        result['rows_per_second'] = result['rows_returned']/max(result['elapsed_seconds'],.001)
        result['negative_sample'] = negative
        _queue.put({'type':'done','checkpoint':result},timeout=120)
    return {'key':key,'status':result['status']}


def persist_handoff(store, path, root):
    path = Path(path).resolve()
    if not path.is_relative_to((root/'tmp/worker_results').resolve()):
        raise ValueError('Handoff outside task temporary result directory')
    message = load_json(path)
    store.put_records(message['records'])
    store.put_hits(message['hits'])
    c = message['checkpoint']
    store.checkpoint(c['key'],'discovery',c['path'],'partial',c['rows_returned'],c)
    path.unlink()  # only this reconstructible handoff, after durable catalog writes
    return c


def scan_parallel(cfg):
    root = Path(cfg['data_root'])
    (root/'tmp/worker_results').mkdir(exist_ok=True)
    queries = load_json(root/'inputs/keywords.json')
    query_hash = digest(queries)
    manifest = load_json(root/'inputs/source_manifest.json')['files']
    files = select_files(cfg,manifest,'discovery')
    ledger = Ledger(cfg)
    ledger.check_time()
    store = Store(cfg)  # the single writer; also ensures cached httpfs is installed
    store.recover()
    for handoff in sorted((root/'tmp/worker_results').glob('*.json')):
        persist_handoff(store,handoff,root)
    relay = Relay(cfg,manifest,ledger)
    start = time.monotonic()
    last_accounted = start
    deadline = start + cfg['resources']['max_query_seconds'] - ledger.data['query_seconds']
    relay.deadline = deadline
    run_id = 'discovery_parallel_' + now().replace(':','-')
    results, pending, negative = {}, [], load_json(root/'inspection/keyword_negative_sample.json',[])
    negative_ids = {r['typed_id'] for r in negative}
    for f in files:
        key = digest({'revision':f['revision'],'path':f['path'],'stage':'discovery','scope':cfg['discovery'],
                      'query_hash':query_hash,'matcher_version':VERSION,'target_hash':None})
        if store.completed(key):
            row = store.db.execute('SELECT json FROM checkpoints WHERE key=?',[key]).fetchone()
            c = json.loads(row[0])
            c.update(status='previously_complete',key=key)
            results[key] = c
        else:
            pending.append({'key':key,'file':f,'url':relay.url(f),'deadline':deadline,'query_hash':query_hash,'run_id':run_id})
    report = {'run_id':run_id,'stage':'discovery','started':now(),'selected_paths':[f['path'] for f in files],
        'query_hash':query_hash,'scope':cfg['discovery'],'workers':cfg['resources'].get('workers',4),
        'writer_count':1,'query_time_basis':'Wall-clock elapsed active coordinated scan; not sum of overlapping worker CPU times',
        'transfer_definition':'Shared relay measures upstream HTTP payload; excludes headers/TLS/TCP/OS read-ahead',
        'files':[]}
    context = multiprocessing.get_context('spawn')
    messages = context.Queue(maxsize=32)
    cancel = context.Event()
    executor = concurrent.futures.ProcessPoolExecutor(max_workers=cfg['resources'].get('workers',4),mp_context=context,
        initializer=_initialize,initargs=(queries,messages,cfg,cancel))
    active = {}
    done_received = set()
    next_job = 0
    last_save = 0
    last_disk = time.monotonic()
    stopped = None
    def save_progress():
        nonlocal last_accounted, last_save
        current = time.monotonic()
        ledger.data['query_seconds'] += current-last_accounted
        last_accounted = current
        ledger.flush()
        completed = [c for c in results.values() if c['status'] in ('complete','previously_complete')]
        report['files'] = list(results.values())
        report['elapsed_seconds'] = current-start
        save_json(root/'logs'/(run_id+'.json'),report)
        save_json(root/'state/live_progress.json',{'run_id':run_id,'stage':'discovery','active':True,'updated_at':now(),
            'selected_shards':len(files),'processed_shards':len(results),'complete_shards':len(completed),
            'records_in_complete_shards':sum(c.get('rows_returned',0) for c in completed),
            'keyword_hits_in_complete_shards':sum(c.get('phrase_hits',0) for c in completed),
            'active_files':[job['file']['path'] for job in active.values()],
            'workers':cfg['resources'].get('workers',4),'payload_bytes_cumulative':ledger.data['payload_bytes'],
            'query_seconds_cumulative':ledger.data['query_seconds']})
        last_save = current
    try:
        store.bulk('query_definitions',[dict(query_id=q['query_id'],json=dumps(q)) for q in queries])
        while active or next_job < len(pending):
            current = time.monotonic()
            if current >= deadline:
                stopped = 'seven_hour_query_ceiling'
            if (root/'state/stop_requested').exists():
                stopped = 'requested_stop'
            if ledger.data['payload_bytes'] >= cfg['resources']['network_bytes'] - 100000000:
                stopped = 'network_budget'
            if stopped:
                cancel.set()
                relay.deadline = time.monotonic()
            while not stopped and len(active) < cfg['resources'].get('workers',4) and next_job < len(pending):
                job = pending[next_job]; next_job += 1
                job['payload_start'] = ledger.data.get('payload_bytes_by_source',{}).get(job['file']['path'],0)
                active[executor.submit(_read_file,job)] = job
            if stopped and not active:
                break
            try:
                message = messages.get(timeout=.2)
            except queue.Empty:
                message = None
            if message:
                if message['type']=='batch':
                    c = persist_handoff(store,message['path'],root)
                else:
                    c = message['checkpoint']
                    samples = c.pop('negative_sample',[])
                    for r in samples:
                        if r['typed_id'] not in negative_ids:
                            negative.append(r); negative_ids.add(r['typed_id'])
                    store.checkpoint(c['key'],'discovery',c['path'],c['status'],c['rows_returned'],c)
                results[c['key']] = c
                if message['type']=='done':
                    job = next((v for v in active.values() if v['key']==c['key']),None)
                    if job:
                        c['payload_bytes'] = ledger.data.get('payload_bytes_by_source',{}).get(c['path'],0)-job['payload_start']
                        store.checkpoint(c['key'],'discovery',c['path'],c['status'],c['rows_returned'],c)
                    done_received.add(c['key'])
                    print(dumps({'path':c['path'],'status':c['status'],'rows':c['rows_returned'],'hits':c['phrase_hits'],'seconds':round(c['elapsed_seconds'],2)}),flush=True)
            for future, job in list(active.items()):
                if future.done():
                    exception = future.exception()
                    if exception:
                        c = results.get(job['key'],{'path':job['file']['path'],'key':job['key'],'kind':job['file']['kind'],'stage':'discovery','rows_returned':0})
                        c.update(status='failed',error=type(exception).__name__+': '+str(exception))
                        results[job['key']] = c
                        store.checkpoint(c['key'],'discovery',c['path'],'failed',c['rows_returned'],c)
                        del active[future]
                    elif job['key'] in done_received:
                        del active[future]
            if current-last_save >= 5:
                save_progress()
            if current-last_disk >= 30:
                check_disk(cfg); last_disk=current
    finally:
        # No queued archive-sized backlog: at most worker_count active readers.
        cancel.set()
        if active:
            relay.deadline = time.monotonic()
        # Drain IPC while readers exit; preserve handoff files until catalogued.
        deferred_messages = []
        while any(not future.done() for future in active):
            try:
                deferred_messages.append(messages.get(timeout=.2))
            except queue.Empty:
                pass
        executor.shutdown(wait=True,cancel_futures=True)
        try:
            while True:
                deferred_messages.append(messages.get_nowait())
        except queue.Empty:
            pass
        try:
            for message in deferred_messages:
                if message['type']=='batch':
                    c = persist_handoff(store,message['path'],root)
                else:
                    c = message['checkpoint']
                    c.pop('negative_sample',None)
                    store.checkpoint(c['key'],'discovery',c['path'],c['status'],c['rows_returned'],c)
                results[c['key']]=c
            save_progress()
            report['complete'] = len(results)==len(files) and all(c['status'] in ('complete','previously_complete') for c in results.values())
            report['stop_reason'] = stopped or ('selected_files_exhausted' if report['complete'] else 'failed_files_remain')
            report['finished'] = now()
            report['disk_bytes'] = disk_usage(root)
            save_json(root/'logs'/(run_id+'.json'),report)
            save_json(root/'inspection/keyword_negative_sample.json',negative)
            store.db.execute('INSERT OR REPLACE INTO runs VALUES (?,?)',[run_id,dumps(report)])
            progress=load_json(root/'state/live_progress.json')
            progress.update(active=False,complete=report['complete'],stop_reason=report['stop_reason'],finished_at=now())
            save_json(root/'state/live_progress.json',progress)
        finally:
            messages.close(); relay.close(); store.close()
    return report
