# Pipeline operations

Machine-specific setup and commands, separated from the shareable research README. Run only the workflow appropriate to the active task; the original collection and continuation have separate state and outputs.

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

## Verification commands

```powershell
.\.venv-research\Scripts\python.exe -m pytest -q
.\.venv-research\Scripts\python.exe -m tools.validate_matcher
.\.venv-research\Scripts\python.exe -m tools.validate_native_prefilter
```
