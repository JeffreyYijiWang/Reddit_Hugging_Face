"""Check the necessary native filter without reading remote source data."""
import json
import unicodedata
from pathlib import Path

import duckdb
import pyarrow as pa

from reddit_reid.keywords import Matcher

queries = json.loads(Path('data/inputs/keywords.json').read_text(encoding='utf-8'))
matcher = Matcher(queries)
texts = []
for q in queries:
    phrase = q['normalized']
    texts.extend([
        phrase,
        phrase.upper().replace(' ', '\t  '),
        phrase.replace('recognized', 'recognised').replace("'", '’'),
        ''.join(chr(ord(c)+0xfee0) if 'a' <= c <= 'z' else c for c in phrase),
    ])
phrase_cases = len(texts)
compat = [chr(n) for n in range(128, 0x110000)
          if any('a' <= c <= 'z' for c in unicodedata.normalize('NFKC', chr(n)).casefold())]
texts.extend(compat)
db = duckdb.connect(':memory:')
db.register('examples', pa.table({'text': texts}))
misses = db.execute("SELECT text FROM examples WHERE NOT regexp_matches(text, ?, 'i')", [matcher.coarse_pattern()]).fetchall()
assert not misses, misses[:10]
print(json.dumps({'phrase_variants': phrase_cases, 'unicode_compatibility_characters': len(compat),
                  'native_prefilter_false_negatives': len(misses), 'anchor_words': sorted(matcher.anchor_words)}))
