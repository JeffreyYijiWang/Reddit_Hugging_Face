"""Read-only corpus checks, plus an independent C: recovery snapshot."""
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

root = Path(__file__).resolve().parents[1]
backup = Path('C:/Users/Jeffr/.codex/visualizations/2026/09/25/01a0d6bb-8265-7140-b144-bc15875ac68b/reddit-recovery') / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup.mkdir(parents=True, exist_ok=False)
db = duckdb.connect(str(root/'data/state/research.duckdb'), read_only=True, config={'memory_limit':'512MB','threads':1})
rows = db.execute('SELECT typed_id,content_hash,json,canonical_file FROM records').fetchall()
files = sorted({r[3] for r in rows})
errors = []
for rid, expected, raw, filename in rows:
    record = json.loads(raw)
    serialized = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8')
    if hashlib.sha256(serialized).hexdigest() != expected:
        errors.append({'id':rid,'error':'record content hash mismatch'})
for filename in files:
    try:
        pq.ParquetFile(root/'data'/filename).metadata
    except Exception as exc:
        errors.append({'file':filename,'error':str(exc)})
counts = dict(db.execute('SELECT kind,count(*) FROM records GROUP BY kind').fetchall())
db.close()
to_copy = [root/'data/state/research.duckdb', root/'data/state/resource_ledger.json', root/'data/inputs/source_manifest.json', root/'data/inputs/keywords.json', root/'data/inputs/review_overrides.json', root/'config.yaml', root/'codebook.md']
to_copy += list((root/'reddit_reid').glob('*.py'))
copied = []
for source in to_copy:
    target = backup/source.relative_to(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(target.read_bytes()).digest():
        raise RuntimeError('Backup checksum mismatch: '+str(source))
    copied.append(str(source.relative_to(root)))
report = {'checked_at':datetime.now(timezone.utc).isoformat(), 'counts':counts, 'record_hashes_checked':len(rows), 'parquet_footers_checked':len(files), 'errors':errors, 'backup':str(backup), 'backup_files':copied, 'interpretation':'All catalogued record hashes and referenced Parquet footers checked. This is not a physical drive health certification.'}
(backup/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
if errors:
    raise SystemExit(1)
