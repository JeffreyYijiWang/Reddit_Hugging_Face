# Reddit re-identification research

This project searches archived Reddit posts and comments for first-person reports of re-identification: for example, reports that someone connected an online post or account to a person they know. Hugging Face hosts the source dataset; our Python pipeline reads the archive, searches it with the researcher's 7,886 keyword phrases, and saves candidate records for evidence-based review.

**Source:** [Dk587/arctic on Hugging Face](https://huggingface.co/datasets/Dk587/arctic), pinned to revision `cd44b72689d409b6a881e0b4581d106b9c37a613`. The findings below describe the files inventoried and sampled at that revision. They do not assume the repository is a complete archive of Reddit or that it has the same contents as other Arctic repositories.

**Current scan setup:** the original run used a seven-hour cumulative query ceiling. The separate continuation in `config.remaining.yaml` has **no query time limit**, reuses verified completed files, excludes earlier candidate IDs, and writes to a separate review workbook. Its scope remains the 3,308 files in the pinned `Dk587/arctic` snapshot; the larger `open-index/arctic` repository is outside that scan. See [Remaining archive scan](REMAINING_SCAN.md). Submissions are searched first, then comments. Searching comment text and retrieving every comment for a particular thread are separate operations.

## Dataset overview for research collaborators

### 1. What does it contain?

The dataset supplies archived Reddit records and their metadata. It has two record types:

| Record type | What one row represents | Main text fields | Files | Compressed size | First and last available file months |
|---|---|---|---:|---:|---|
| Submissions | One Reddit post, including text posts and posts linking to other content | `title`, `selftext` | 2,533 | 162.53 GB | December 2005–February 2026, with substantial gaps |
| Comments | One comment or reply | `body` | 775 | 32.17 GB | December 2005–August 2012 |
| Total | Both record types | | 3,308 | 194.70 GB | Coverage differs by type |

Sizes use decimal GB and describe the inventoried remote files, not the size of our saved keyword results. The dates describe available file partitions; the presence of a month's files does not establish that every record from that month is included. Submission coverage includes a missing June 2011 partition and large gaps after 2013. The complete month lists and file sizes are in [the inventory summary](data/inspection/inventory_summary.json) and [the source manifest](data/inputs/source_manifest.json).

**How this relates to the terabyte-scale archive (checked September 25, 2026).** The 194.70 GB figure is the total for our selected snapshot, not for all Arctic Shift data. The [Dk587 dataset card's coverage section](https://huggingface.co/datasets/Dk587/arctic#coverage), last updated March 25, 2026, reports a 3.6 TB source archive, 493.0 GB processed, and 3.1 TB still awaiting conversion. Those source figures refer to compressed `.zst` JSONL and include both submissions and comments. They describe that publisher's conversion progress at the time, not our search progress or 3.1 TB of posts alone.

The separate [open-index/arctic repository](https://huggingface.co/datasets/open-index/arctic) has substantially more Parquet data. We checked its file metadata at revision `da567f9441c5a7ebf02d13eeeaa020b11f321f8d`:

| Repository snapshot | Post files | Comment files | Total compressed Parquet size |
|---|---:|---:|---:|
| `Dk587/arctic`, used by our scan | 2,533 | 775 | 194.70 GB |
| `open-index/arctic`, newly checked | 5,783 | 26,031 | 1,478.46 GB (1.478 TB) |

Both rows use decimal units and sums of file sizes. Source `.zst` sizes and converted Parquet sizes measure different representations and coverage. Publisher CSV totals also differ slightly from actual file metadata, so we retain the measured inventory separately. The comparison and source metadata are saved in [the size audit](data/inspection/archive_size_comparison_2026-09-25.json). Completing our current continuation will finish its selected snapshot, subject to reported failures; it will not establish coverage of the larger repository.

The archive includes general Reddit content across topics. Re-identification labels, evidence selections, and research categories are added by this project after retrieval. A keyword match is a candidate for review, not a confirmed incident.

### 2. Is there real text, and can we retrieve posts?

**Yes.** The executed inspection read five actual rows from each of six files: early, middle, and recent available periods for each record type. These were reads from Parquet files, not examples copied from a dataset description.

- All 15 sampled submissions had title text. In the five February 2026 submissions, three had body text and two had `[removed]` placeholders. The ten earlier sampled submissions had empty `selftext` fields.
- Fourteen of the 15 sampled comments contained body text; one contained a deletion/removal placeholder.
- These 30 rows demonstrate that text is present. Their selection was deterministic and small, so these proportions do not estimate text availability across the archive.

For a compact real example, the August 2012 sample contains a comment in `australia` with the body: “everything checks out here, move along.” It also includes the comment's ID, parent ID, containing post ID, timestamp, and score. Full sample records, schemas, executed SQL, and text-availability counts are saved in [samples.json](data/inspection/samples.json).

**Post retrieval was also tested.** A December 2005 experiment looked up five submission IDs and retrieved all five posts, plus one linked comment for each. There were no failed submission joins in that experiment. See [the join demonstration](data/inspection/join_demonstration.json).

The retrieval relationships are:

- A submission's `id` identifies the post.
- A comment's `link_id` identifies its containing post, typically as `t3_<post_id>`.
- A comment's `parent_id` identifies the post or comment it directly replies to.

These fields let us retrieve archived posts by ID and group comments into threads when the relevant records are present. They do not guarantee a fast indexed lookup; a query may still need to scan large files. Retrieving an archived record also does not establish that its page is accessible on Reddit today.

### 3. What does the dataset look like?

It is a collection of **Parquet tables**, a compressed column-based file format. Each file is a shard: one chunk of records. Files are organized by record type, year, and month, for example:

```text
data/submissions/2026/02/000.parquet
data/comments/2012/08/000.parquet
```

Posts and comments live in separate tables. A post's comments are connected through IDs rather than embedded inside its row. Several inspected files contained 500,000 rows; smaller early files contained fewer. We have not inferred the archive's total row count by multiplying the file count by 500,000.

The inspected schemas include:

| Fields | Present in inspected schemas | Meaning |
|---|---|---|
| `id`, `author`, `subreddit` | Posts and comments | Record ID, archived author value, and community name |
| `created_utc`, `created_at` | Posts and comments | Creation time as Unix seconds and a timestamp |
| `score` | Posts and comments | Archived score; separate upvote and downvote totals are not supplied |
| `title`, `selftext` | Posts | Post title and body text; body may be empty or a placeholder |
| `url`, `num_comments` | Posts | Submitted URL and archived comment-count value; a URL may point outside Reddit |
| `over_18`, `link_flair_text`, `author_flair_text` | Posts | Available content flags and flair metadata |
| `body`, `link_id`, `parent_id` | Comments | Comment text, containing post, and immediate parent |
| `distinguished`, `author_flair_text` | Comments | Available comment/author metadata |
| `title_length` / `body_length` | Posts / comments | Stored text-length metadata |

Schemas are verified for sampled or subsequently inspected files; the reader checks each file's available columns. Our local exports add fields such as canonical permalinks, source-file provenance, matching phrases, collection coverage, and review status. Those added fields should be distinguished from fields supplied by the archive.

### 4. Does it include subreddits?

**Yes. Both sampled posts and comments have a `subreddit` column.** Observed examples include `AskReddit`, `pics`, `technology`, `PowerShell`, `Music`, and `nba`. These are examples from the inspection, not an exhaustive list or a ranking of community sizes.

The column supports filtering to selected communities and grouping retrieved results by subreddit. The current discovery configuration searches all available communities; an empty subreddit filter means no community restriction. Comparing communities still requires accounting for unequal time coverage, missing records, and which files were successfully searched.

### What this makes possible for our study

We can search archived titles, post bodies, and comments with the workbook phrases; retain the full available matching text and metadata; retrieve related archived records by ID; and prepare a reproducible collection for qualitative review. Every retained match can be traced to its query and source file.

The principal limitation for newer cases is the date mismatch: a 2025 or 2026 post may be available while its comments are outside this repository's comment coverage. Empty text, `[deleted]`/`[removed]` placeholders, and absent threads remain explicit missing data. The inspected schemas also do not supply account creation dates, complete lifetime activity histories, historical weekly subreddit visitors/contributors, or current account/post status. A stored `num_comments` value is not evidence that we retrieved that many comments.

For a coworker: “We are searching a version-pinned, 194.7 GB subset of the Arctic Shift Reddit archive hosted on Hugging Face. It contains real post and comment text, subreddit names, timestamps, scores, and IDs that connect comments to posts. A separate Hugging Face repository contains about 1.48 TB of Parquet data, beyond our current scan. Our code searches the selected subset for first-person re-identification reports and saves candidates for review. Its post and comment coverage differs, so we document missing context and do not treat keyword hits as confirmed incidents.”

## Results and live state

The original collection and the continuation have independent state and outputs:

| Run | Progress and completion | Review output |
|---|---|---|
| Original collection | `data/state/live_progress.json`, `data/state/full_run_status.json` | `data/exports/research_review.xlsx` and numbered parts |
| Remaining archive continuation | `data_remaining/state/live_progress.json`, `data_remaining/state/full_run_status.json` | `outputs/01a0d7fb-20a1-75c2-83ec-202ecae1a0ed/review_remaining.xlsx` and numbered parts if needed |

Read both progress and completion state before reporting coverage. An Excel workbook is an exported snapshot and can lag behind an active scan. The continuation's completion records include imported earlier coverage, while its candidate rows exclude the 23,209 candidate IDs present at the continuation boundary.

Original-run files:

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

# Continue the remaining archive without a query time ceiling; separate state/output
.\start-remaining-scan.ps1

# Original archive run; seven-hour cumulative ceiling; writes original state/output
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

The original large run used four reader processes with 512 MB engine limits and a coordinator with a 2 GB engine limit. After its resource failure, the continuation was configured with two readers at 384 MB each, one DuckDB thread per reader, and a coordinator with a 512 MB engine limit. Readers hand off distinct durable files; only the coordinator writes its run's `research.duckdb`. The 1 GB spill allowance is divided among readers, and each configured data root has a 5 GB ceiling. Python/Arrow allocations are not all governed by engine limits, so RSS is sampled separately. Query time means elapsed coordinated wall time, not summed overlapping worker durations. Removing the continuation's time ceiling leaves its network, storage, memory, and individual-request limits in place. A loopback relay allows only manifest URLs, uses verified TLS with the OS certificate store, forwards range requests and counts consumed HTTP payload. It refuses unbounded full-file responses to range requests. Bytes exclude headers/TLS/TCP and OS read-ahead; this is not a strict wire-byte guarantee. Metadata API responses are counted. Dependency/paper downloads, the initial metadata probe and extension installation are setup traffic outside the ledger.

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

The resumed review uses the signed-in ChatGPT account through the project-local Codex CLI 0.157.0, with the explicitly resolved `gpt-6-astra` model and medium reasoning effort. No API key is required for this route. `reddit_reid.chatgpt_review` supplies full retained source text, validates record coverage and exact evidence quotes, and stores content-hash-bound model-generated annotations in `data/chatgpt_reviews`. Missing source text remains explicitly missing; oversized cases are held for review without truncation. Four calibration examples and four separately sampled negative cases passed engineering checks; these are assistant references, not human adjudication or a population accuracy estimate. See `data/inputs/chatgpt_qualification.json` for the qualification limits.

The current `start-research-review.ps1` supervisor collects archived context, rebuilds case bundles, runs a bounded classifier session, then exports the available reviews with pending cases preserved. This original run retains its cumulative seven-hour query ledger. The separately authorized continuation described in `REMAINING_SCAN.md` handles unfinished discovery under its own configuration and ledger. `tools/avoid_duplicate_discovery.py` waits for this run's context query to finish before creating `data/state/stop_requested`, preventing duplicate discovery while allowing ChatGPT review and export to continue. It does not touch `data_remaining`. Progress is recorded in `data/state/resumed_research_status.json`, `review_context.json`, `discovery_coordination.json`, and `chatgpt_review_progress.json`.

An alternative API classifier can be enabled by configuring `model.endpoint` (a chat-completions-compatible endpoint), `model.name`, and the environment variable named by `model.api_key_env`. Keys never enter tracked files. API compatibility remains unverified because no credentials were supplied.

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
