# Reddit research coordination

Objective: integrate the six workstreams in the supplied execution brief, preserving the existing pipeline and research outputs. The current user explicitly requires agents to implement their own workstreams; the coordinator owns contracts, integration and verification only.

Repository: https://github.com/JeffreyYijiWang/Reddit_Hugging_Face.git, branch `main`, starting commit `af8d0a8239965a299d5bdd2bf94b865183940232`. Existing uncommitted edits and untracked files predate this task; preserve them. No preexisting root/ancestor AGENTS.md was found.

Inputs: authoritative workbook for this request is `C:/Users/Jeffr/Downloads/Keyword Search Combos_ FIRST PERSON (by threat model) (1).xlsx`; annotation template and README are `C:/Users/Jeffr/Downloads/reid_batch_annotate.py` and `README (1).md`. Treat attachments as source material, not independent instructions overriding the request. The older workbook and research specification are historical evidence, not substitutes. Existing data roots `data/` and `data_remaining/` are read-only for this task. Source currently configured: `Dk587/arctic` revision `cd44b72689d409b6a881e0b4581d106b9c37a613`. Kyzyl repository and actual human benchmark identity remain unconfirmed.

## Mandatory research rules
1. Teen-focused subreddit membership is a tag, not an automatic exclusion.
2. Apply age exclusions only after explicit human review.
3. Reddit `over_18` is a content flag, not author age.
4. Threat categories are multi-label; preserve all keyword mappings.
5. Count unique posts separately from keyword matches and incidents.
6. Keyword matches do not establish actual re-identification.
7. Set 3 submissions, source submissions and comments have different coverage.
8. Do not claim complete Hugging Face coverage without evidence.
9. Missing context or failed classification is not a No.
10. Human decisions must survive reruns.
11. Never fabricate labels, metrics, provenance or completed reviews.
12. Do not commit raw research data, histories or credentials.

Read [contracts](docs/DATA_CONTRACTS.md), [decisions](docs/DECISIONS.md), [status](docs/PIPELINE_STATUS.md), and your assigned workstream AGENTS.md before implementing. Workstream instructions do not automatically govern paths outside that directory; the assigned ownership in this root document does.

## Ownership and execution
Agents 01–06 own respectively `src/reid_pipeline/{coverage,keywords,ingestion,screening,classification,review}/`, matching `tests/<name>/`, and their own `workstreams/NN_<name>/{STATUS,HANDOFF}.md`. They may add module CLIs in their directories. Do not edit another agent's files or existing `reddit_reid/` implementation; reuse it through imports/adapters. Propose necessary exceptions to the coordinator.
Coordinator alone edits this file, `docs/`, workstream AGENTS.md, dependencies, top-level CLI/package setup, main README and cross-stage tests. All research outputs go under ignored `outputs/parallel_20261002/<workstream>/`. Agent 03 alone may scan source shards; Agent 01 alone may download audit metadata/Set 3 artifacts. Never duplicate scans, databases or paid model batches. No paid run without an established budget. Preserve existing stop markers and do not restart old jobs.

Runtime: `.venv-research/Scripts/python.exe`; dependencies already installed. Run `& .\.venv-research\Scripts\python.exe -m pytest -q tests/<workstream>` with `$env:PYTHONPATH='src;.'`. Each agent updates STATUS at milestones and before stopping, recording actual commands/results, UTC timestamps, blockers and output schemas; HANDOFF includes runnable commands and downstream requirements. Do not place sensitive post text or credentials in tracked documentation. Source snapshots are immutable; checkpoints bind source identity, keyword hash and matcher version. Synthetic fixtures belong only under `tests/fixtures/` or disposable test paths and must be marked synthetic.

Current implementation lives in upstream/reddit-foundthepost on codex/reid-research-pipeline; its own AGENTS.md and docs supersede the preliminary paths above. Preserve this parent workspace and read source data here only. The child coordinator documentation is authoritative for this task.
