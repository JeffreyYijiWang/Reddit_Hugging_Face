"""Differential check of the acceleration prefilter against the full matcher."""
import json
from pathlib import Path
from reddit_reid.keywords import Matcher

queries = json.loads(Path('data/inputs/keywords.json').read_text(encoding='utf-8'))
fast, reference = Matcher(queries), Matcher(queries)
reference.prefilter_enabled = False
tested = 0
for q in queries:
    phrase = q['normalized']
    variants = [phrase, phrase.upper().replace(' ', '\t  '), phrase.replace('recognized','recognised').replace("'",'’'),
                ''.join(chr(ord(c)+0xfee0) if 'a' <= c <= 'z' else c for c in phrase)]
    for value in variants:
        text = 'before: ' + value + ' after.'
        assert fast.find(text) == reference.find(text), q['query_id']
        tested += 1
print(json.dumps({'queries': len(queries), 'differential_cases':tested, 'mismatches':0}))
