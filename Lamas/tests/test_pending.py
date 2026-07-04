from lamas.headers.mapping import HeaderMapping
from lamas.headers.pending import resolve_headers


def _mapping(tmp_path, canon_to_orig):
    m = HeaderMapping({}, tmp_path / 'm.yaml')
    for canon, origs in canon_to_orig.items():
        for o in origs:
            m.add_mapping(canon, o)
    return m


def test_exact_match_resolved_no_pending(tmp_path):
    m = _mapping(tmp_path, {'canon': ['raw']})
    rows = [{'header': 'raw', 'year': 2020, 'sheet': 's', 'value': '1'}]
    resolved, pending = resolve_headers(rows, m)
    assert resolved[0]['header'] == 'canon'
    assert resolved[0]['orig_header'] == 'raw'
    assert pending == {}


def test_unresolved_header_left_unchanged_and_recorded(tmp_path):
    m = _mapping(tmp_path, {'canon': ['totally different text']})
    rows = [{'header': 'brand new header', 'year': 2020, 'sheet': 's', 'value': '1'}]
    resolved, pending = resolve_headers(rows, m)
    assert resolved[0]['header'] == 'brand new header'
    entry = pending['brand new header']
    assert entry['status'] == 'unresolved'
    assert entry['count'] == 1
    assert entry['years'] == {2020}


def test_fuzzy_match_auto_resolves_but_still_recorded(tmp_path):
    # These two strings differ only by a colon vs dash punctuation - a real near-duplicate
    # pattern found during exploration; fuzz.ratio scores it well above the 95 threshold.
    m = _mapping(tmp_path, {
        'ארנונה למגורים - גבייה השנה (קרן + ריבית)': ['ארנונה למגורים - גבייה השנה (קרן + ריבית)'],
    })
    rows = [{'header': 'ארנונה למגורים: גבייה השנה (קרן + ריבית)', 'year': 2020, 'sheet': 's', 'value': '1'}]
    resolved, pending = resolve_headers(rows, m)
    assert resolved[0]['header'] == 'ארנונה למגורים - גבייה השנה (קרן + ריבית)'
    entry = pending['ארנונה למגורים: גבייה השנה (קרן + ריבית)']
    assert entry['status'] == 'auto_resolved_needs_confirmation'
    assert entry['suggested_canonical'] == 'ארנונה למגורים - גבייה השנה (קרן + ריבית)'


def test_aggregates_across_multiple_rows_for_same_orig_header(tmp_path):
    m = HeaderMapping({}, tmp_path / 'm.yaml')
    rows = [
        {'header': 'new header', 'year': 2020, 'sheet': 'a', 'value': '1'},
        {'header': 'new header', 'year': 2021, 'sheet': 'b', 'value': '2'},
    ]
    _, pending = resolve_headers(rows, m)
    entry = pending['new header']
    assert entry['count'] == 2
    assert entry['years'] == {2020, 2021}
    assert entry['sheets'] == {'a', 'b'}
