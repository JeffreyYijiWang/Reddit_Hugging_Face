"""Render a clearly marked layout sample against an independent DB snapshot."""
import importlib
from pathlib import Path

from reddit_reid.common import load_config

backup_root = Path('C:/Users/Jeffr/.codex/visualizations/2026/09/25/01a0d6bb-8265-7140-b144-bc15875ac68b/reddit-recovery/20260925T113944Z')
cfg = load_config(backup_root/'config.yaml')
cfg['export']['max_rows_per_workbook'] = 1000000
module = importlib.import_module('reddit_reid.export')
def sample(tables,max_rows):
    selected = {name:{'headers':table['headers'],'rows':table['rows'][:6]} for name,table in tables.items()}
    selected['Summary']['rows'] = [['Purpose','Layout QA sample only; not the full research result']] + selected['Summary']['rows']
    yield 1,selected,{}
module.workbook_parts = sample
print(module.export(cfg))
