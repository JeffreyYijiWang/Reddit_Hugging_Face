import unicodedata

import pytest

from reddit_reid.keywords import Matcher, normalize, normalized_offsets


@pytest.mark.parametrize('source', [
    '\u1100\u1161\u11a8',  # Hangul L/V/T composition; CCC=0
    '\u09c7\u09be',       # Bengali vowel-sign composition; CCC=0
    'a\u1ab0\u0323',      # Canonical reordering across combining blocks
    '\ufb03\u0301',       # Compatibility expansion followed by a mark
    '\u0f71\u0f73',       # Tibetan decomposition and combining order
])
def test_non_latin_context_does_not_break_exact_keyword_offsets(source):
    phrase = 'found my post'
    text = source + '  FOUND\tmy\npost ' + source
    value, spans = normalized_offsets(text)
    assert value == normalize(text)
    assert len(spans) == len(value)
    hit, = Matcher([{'query_id': 'synthetic', 'normalized': phrase}]).find(text)
    assert hit['quote'] == 'FOUND\tmy\npost'
    assert text[hit['start']:hit['end']] == hit['quote']


def test_canonical_decompositions_preserve_normalization_and_source_spans():
    # Exercise every canonically decomposable code point, including Hangul.
    samples = [unicodedata.normalize('NFD', chr(code)) for code in range(0x110000)
               if unicodedata.normalize('NFD', chr(code)) != chr(code)]
    text = ' | '.join(samples)
    value, spans = normalized_offsets(text)
    assert value == normalize(text)
    assert len(value) == len(spans)
    assert all(0 <= start < end <= len(text) for start, end in spans)
