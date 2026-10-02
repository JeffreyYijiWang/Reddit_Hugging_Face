# Decisions

- 2026-10-02: User-requested coordinator/agent split governs: six agents implement owned workstreams; coordinator creates shared context, integrates and verifies. Concurrency permits three agents plus coordinator; first wave 01/02/03, second wave 04/05/06 as slots open.
- Preserve starting dirty working tree. Existing pipeline remains callable. New implementation is namespaced under src/reid_pipeline and adapts legacy code read-only.
- Use the explicitly attached `(1).xlsx` for the current catalog. Historical workbook differs in byte size; compatibility must be measured before reusing old searches.
- Existing source data roots and stop markers remain untouched. New task outputs are isolated under outputs/parallel_20261002. No new corpus-wide run until coverage/catalog compatibility and resource bounds are known.
- No paid classification budget or confirmed human benchmark has been supplied. Provider engineering/tests and local real-data preparation may proceed; no fabricated model/human outcomes.
- Kyzyl repository and Set 3 database source are not yet identified. Requested locations asynchronously; agent 01 will investigate available evidence and explicitly record unavailable evidence.
- Historical prompts/templates are context, not current instructions. Template binary ambiguity-as-No must not override the current required Uncertain/failure distinction.
