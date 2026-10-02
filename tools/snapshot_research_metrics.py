"""Read a closed continuation snapshot without disturbing an active scan."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

import duckdb


def snapshot(project: Path, snapshot_dir: Path) -> dict:
    manifest = json.loads((project / 'data_remaining/inputs/source_manifest.json').read_text())
    prior = set(json.loads((project / 'data_remaining/inputs/prior_candidate_ids.json').read_text()))
    progress = json.loads((snapshot_dir / 'live_progress.json').read_text())
    db = duckdb.connect(str(snapshot_dir / 'research.duckdb'), read_only=True,
                        config={'memory_limit': '128MB', 'threads': 1})
    try:
        rows = db.execute('SELECT stage,path,status,scanned FROM checkpoints').fetchall()
        retained = db.execute('SELECT DISTINCT r.typed_id,r.kind FROM records r JOIN hits h USING(typed_id)').fetchall()
        hit_ids = {row[0] for row in db.execute('SELECT DISTINCT typed_id FROM hits').fetchall()}
    finally:
        db.close()
    new_ids = {row[0] for row in retained}
    assert hit_ids == new_ids, 'Some matching records are not retained.'
    assert not prior.intersection(new_ids), 'Earlier and continuation candidates overlap.'
    complete = [row for row in rows if row[0] == 'discovery' and row[2] == 'complete']
    assert len({row[1] for row in complete}) == len(complete), 'Duplicate file coverage.'
    assert sum(row[3] for row in complete) == progress['records_in_complete_shards']
    assert len(complete) == progress['complete_shards']
    before = Counter('submissions' if i.startswith('t3_') else 'comments' if i.startswith('t1_') else 'unknown' for i in prior)
    assert 'unknown' not in before
    after = Counter(kind for _, kind in retained)
    metrics = {}
    for kind in ('submissions', 'comments'):
        done = [row for row in complete if row[1].split('/')[1] == kind]
        total_files = sum(f['kind'] == kind for f in manifest['files'])
        metrics[kind] = {
            'scanned_rows_in_completed_files': sum(row[3] for row in done),
            'completed_files': len(done), 'selected_files': total_files,
            'remaining_files': total_files - len(done),
            'original_candidates': before[kind], 'continuation_candidates': after[kind],
            'unique_candidates_collected': before[kind] + after[kind],
        }
    return {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'coverage_checkpoint_utc': progress['updated_at'],
        'source_snapshot': str(snapshot_dir.resolve()),
        'source_repository': manifest['repo'], 'source_revision': manifest['revision'],
        'by_kind': metrics,
        'total': {key: sum(values[key] for values in metrics.values()) for key in metrics['submissions']},
        'interpretation': [
            'Completed discovery files counted once, including imported earlier coverage.',
            'Scanned rows are full-file metadata counts after successful search; partial files excluded.',
            'Candidates are unique matching record IDs, including retained matches from incomplete files.',
            'Context-only records and repeated phrase hits do not add review candidates.',
            'Collected candidates are not necessarily exported or classified yet.',
        ],
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = snapshot(Path(__file__).resolve().parents[1], args.snapshot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
