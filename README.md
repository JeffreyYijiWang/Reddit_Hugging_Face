# Reddit re-identification research

Scans revision-pinned `Dk587/arctic` Parquet files with all 7,886 workbook phrases together. Saves matching full records, exact keyword spans, provenance and resumable checkpoints. No real-identity discovery or independent account linking is performed.

**Current scope:** every available dataset file, with a cumulative seven-hour query ceiling. Submissions run first; comment-text discovery follows if time remains. Full comment reconstruction is optional, following the user's later instruction. The inventory contains 2,533 submission files and 775 comment files (194.70 GB compressed), at revision `cd44b72689d409b6a881e0b4581d106b9c37a613`. Comments stop at August 2012; submissions extend discontinuously through February 2026. This is not complete Reddit coverage.

## Results and live state

- `data/exports/research_review.xlsx`: first review workbook, with all 42 requested columns and appended schema fields. Large exports continue in numbered workbooks; `workbook_manifest.json` lists every part and its global table row ranges. Tables are partitioned independently, with at most 2,000 rows each per workbook.
- `data/exports/research_report.md`: executed inspection, coverage and limitations.
- `data/exports/review.csv`, `posts.csv`, `incidents.csv`, `annotations.jsonl`: local exports.
- `data/state/live_progress.json`: shard-level live progress, safe to read while scanning.
- `data/state/full_run_status.json`: actual PID, run/export status and completion.
- `data/logs/full-run-active-console.txt`: current file completions.
- `data/inputs/source_manifest.json`: complete immutable repository inventory.

The January 2010 pilot completed 3,433,103 records across eight files and retained 47 unique candidates. A separate early-period experiment demonstrated five successful batched post/comment joins. The search then expanded to the whole available archive. Read current coverage rather than assuming every file finished.

No automated classification endpoint/key was supplied. Most candidates therefore remain `Unsure / pending_model_and_human_review`. Four purposive examples were separately reviewed by the interactive assistant using full available seed text (Yes, No and Unsure), with exact evidence and explicit post-only coverage. They await human adjudication and are not an accuracy sample.

## Install

Python 3.12 was used. Dependencies are pinned in `requirements.txt`.

```powershell
python -m venv .venv-research
.\.venv-research\Scripts\python.exe -m pip install -r requirements.txt
.\.venv-research\Scripts\python.exe -m pytest -q
```

On this machine, the bundled Python executable created the environment because the Microsoft Store Python 3.11 launcher was unavailable:

```powershell
& 'C:\Users\Jeffr\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m venv .venv-research
```

XLSX authoring uses the Codex bundled `@oai/artifact-tool` Node package. `config.yaml` contains this machine's Node path; the `node_modules` junction points to bundled dependencies. On another machine, update those paths. CSV/JSON export needs no spreadsheet application. No openpyxl/xlsxwriter authoring is used.

## Commands

Run from this directory. Do not run a second database writer during a scan.

```powershell
# Inspection, workbook audit and selected manifest/cost scope
.\.venv-research\Scripts\python.exe -m reddit_reid inspect --config config.yaml
.\.venv-research\Scripts\python.exe -m reddit_reid import-keywords --config config.yaml
.\.venv-research\Scripts\python.exe -m reddit_reid dry-run --config config.yaml

# Full archive attempt; seven-hour cumulative ceiling; automatic export at end/stop
.\start-full-scan.ps1
# Or run in the foreground:
.\.venv-research\Scripts\python.exe -m reddit_reid run-full --config config.yaml --resume
.\.venv-research\Scripts\python.exe -m reddit_reid search --config config.yaml --resume

# Original smaller pilot and actual join/benchmark demonstrations
.\.venv-research\Scripts\python.exe -m reddit_reid run-pilot --config config.pilot.yaml --resume
.\.venv-research\Scripts\python.exe -m reddit_reid benchmark --config config.pilot.yaml --month 2005-12
.\.venv-research\Scripts\python.exe -m reddit_reid demonstrate-joins --config config.pilot.yaml

# Optional context; explicit earlier/later month scope and 25-case cap
.\.venv-research\Scripts\python.exe -m reddit_reid reconstruct --config config.pilot.yaml --resume

# Local finalization/export; no archive rescan
.\.venv-research\Scripts\python.exe -m reddit_reid finalize --config config.yaml
.\.venv-research\Scripts\python.exe -m reddit_reid annotate --config config.yaml --resume
.\.venv-research\Scripts\python.exe -m reddit_reid export --config config.yaml
.\.venv-research\Scripts\python.exe -m reddit_reid report --config config.yaml
.\.venv-research\Scripts\python.exe -m reddit_reid status --config config.yaml
.\.venv-research\Scripts\python.exe -m reddit_reid recover --config config.yaml
```

Create `data/state/stop_requested` for a graceful stop at a batch boundary, followed by export. Remove that single marker before resuming. The resource ledger persists across restarts: resuming does not grant another seven hours. After the ceiling is exhausted, further querying needs an explicit budget change. A conservative 60-second allowance was charged for the optimization interruption.

## Architecture and budgets

`config.pilot.yaml`: January 2010 discovery, selected because both types are present and costs are manageable; optional December 2009-February 2010 context; 2 GB payload, 20-minute discovery and 25-case reconstruction limits. `config.yaml`: all available months and subreddits, submissions first. Its 220 GB response-payload ceiling supersedes the pilot ceiling after the user requested the entire archive. No paid infrastructure is provisioned.

The full run uses four reader processes, each with one DuckDB thread and a 512 MB engine memory limit, plus one coordinator/database writer. Readers hand off distinct durable files; only the coordinator writes `research.duckdb`. The 1 GB spill allowance is divided among readers. The coordinator retains a 2 GB engine limit and task data have a 5 GB ceiling. Python/Arrow allocations are not all governed by engine limits, so RSS is sampled separately. Query time means elapsed coordinated wall time, not summed overlapping worker durations. A loopback relay allows only manifest URLs, uses verified TLS with the OS certificate store, forwards range requests and counts consumed HTTP payload. It refuses unbounded full-file responses to range requests. Bytes exclude headers/TLS/TCP and OS read-ahead; this is not a strict wire-byte guarantee. Metadata API responses are counted. Dependency/paper downloads, the initial metadata probe and extension installation are setup traffic outside the ledger.

No raw monthly shard cache is enabled. Extension files stay under `data/cache/extensions`. The optional cache allowance is unused and no eviction is needed. Durable research records are never evicted. Canonical Parquet chunks retain typed IDs, thread IDs and full JSON records; writes complete before catalog/checkpoint updates. Raw research data and secrets are excluded from Git.

All queries share one Aho-Corasick automaton. A necessary required-word filter first runs natively in DuckDB, then the exact matcher verifies surviving text. Every phrase contributes an anchor word; British variants are included. Text containing any of the 1,138 non-ASCII characters whose NFKC/casefold introduces ASCII letters bypasses the native word filter. Differential testing of every phrase across four case/whitespace/Unicode/spelling variants produced 31,544 equal results, and the native filter retained all those variants and all compatibility characters. Title/body matching is separate. Raw offsets are reconstructed and validated. A complete shard's scanned-record count uses its verified Parquet metadata count after the filter finishes; partial counts are lower bounds on returned candidates. Filtered convenience negatives are not representative corpus negatives.

Resume keys include repository revision, file, stage, scope, query-set/matcher version and (for context) the target-ID-set hash. Completed shards are skipped. Partial shards restart and deduplicate without remote OFFSET queries. The full run records failures and continues other files while budgets remain; failed/partial files never count as complete. `recover` recatalogs durable orphan chunks, and parallel startup replays unfinished handoff files. A four-file actual-source smoke test verified parallel readers, serial persistence and clean completion.

## Remote query examples

Pass a URL from the resolved manifest as a parameter, never a recursive wildcard. SQL ID joins identify records but do not create an index. `LIMIT` and subreddit filters do not guarantee small bandwidth. Partition selection is explicit; row-group pruning is not assumed.

```sql
SELECT id, title, selftext FROM read_parquet(?) LIMIT 5;
SELECT id, author, subreddit, title, selftext, created_utc
FROM read_parquet(?)
WHERE regexp_replace(id, '^t3_', '') IN (SELECT unnest(?));
SELECT id, author, body, link_id, parent_id, created_utc
FROM read_parquet(?)
WHERE regexp_replace(link_id, '^t3_', '') IN (SELECT unnest(?));
```

The executed equivalents are `inspect` and `demonstrate-joins`; both use the relay and explicit file list. Full inspection SQL, samples and join results are under `data/inspection/`.

## Classification and review

To enable the optional automated classifier, configure `model.endpoint` (a chat-completions-compatible endpoint), `model.name`, and the environment variable named by `model.api_key_env`. Keys never enter tracked files. The implementation uses JSON mode, Pydantic validation, bounded retries, content hashes and exact quote/offset checks. API compatibility remains unverified because no credentials were supplied.

Every batch includes the full available original. Related full posts/comments are segmented with raw offsets and exhaustive coverage records, then reconciled. Oversized originals produce recorded errors, never silent truncation. Unresolved originals remain pending. `data/inputs/review_overrides.json` stores separately authored, content-hash-bound assistant reviews that are validated and preserved when the bundle is unchanged.

`codebook.md` separates the paper's anonymous activities from project post intents and reporter/finder categories. `reddit_reid/schema.py` retains all requested labels and missingness states. Generated machine-readable schema: `data/inputs/annotation.schema.json`. The explicitly synthetic completeness example is outside research cases.

The first 42 Review columns preserve requested order. Seed and original fields are distinct. Unknown originals retain null metadata. “Confirmed URL” means evidence-record URL. Full source text remains in canonical files and CSV; overlong Excel cells refer to complete Text parts. Potential formulas are escaped only in spreadsheet/CSV output. Reviewer labels/notes remain separate editable inputs.

Historical account creation, lifetime pre-post totals and contemporary visitors/contributors/traffic are absent from inspected schemas. Exact up/down vote totals are not derived from score. Missing `is_self` and `upvote_ratio` remain null. Current account/post status is unverified; archived authorship is not current activity. Observed history proxies are separately named. Optional context includes later comment partitions in its declared horizon and explicitly records incomplete scope.

No precision, agreement/confusion matrix or population recall is reported without independent adjudication. Negative convenience examples and four purposive assistant reviews cannot support those estimates. Restricted outputs retain needed Reddit identifiers; public summaries omit case details. Source access restrictions are respected.

## Verification

```powershell
.\.venv-research\Scripts\python.exe -m pytest -q
.\.venv-research\Scripts\python.exe -m tools.validate_matcher
.\.venv-research\Scripts\python.exe -m tools.validate_native_prefilter
```

Tests cover typed IDs, duplicate query memberships, Unicode/raw offsets, negation/hypothetical triage, reporter/finder distinctions, quoted attribution, deleted-author isolation, strict pre-post history, cross-month context, uncertain series links, preservation despite available text, full batching, missing metrics, Excel limits and formula safety. Actual remote joins and XLSX readback provide integration evidence. Synthetic fixtures never enter research results.
