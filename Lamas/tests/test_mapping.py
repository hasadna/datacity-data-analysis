import pytest

from lamas.headers.mapping import DuplicateOrigHeaderError, HeaderMapping


def test_resolve_and_add(tmp_path):
    m = HeaderMapping({}, tmp_path / 'header_mapping.yaml')
    m.add_mapping('canon', 'raw1')
    m.add_mapping('canon', 'raw2')
    assert m.resolve('raw1') == 'canon'
    assert m.resolve('raw2') == 'canon'
    assert m.resolve('unknown') is None


def test_duplicate_orig_header_conflict(tmp_path):
    m = HeaderMapping({}, tmp_path / 'header_mapping.yaml')
    m.add_mapping('canon_a', 'raw1')
    with pytest.raises(DuplicateOrigHeaderError):
        m.add_mapping('canon_b', 'raw1')


def test_readding_same_pair_is_a_noop(tmp_path):
    m = HeaderMapping({}, tmp_path / 'header_mapping.yaml')
    m.add_mapping('canon', 'raw1')
    m.add_mapping('canon', 'raw1')
    assert m.canonical_to_orig['canon'] == ['raw1']


def test_save_load_round_trip(tmp_path):
    path = tmp_path / 'header_mapping.yaml'
    m = HeaderMapping({}, path)
    m.add_mapping('canon', 'raw1')
    m.add_mapping('canon', 'raw2')
    m.save(path)

    m2 = HeaderMapping.load(path)
    assert m2.resolve('raw1') == 'canon'
    assert m2.resolve('raw2') == 'canon'


def test_load_rejects_duplicate_orig_across_canonicals(tmp_path):
    path = tmp_path / 'header_mapping.yaml'
    path.write_text(
        'version: 1\nheaders:\n  a:\n    orig: [x]\n  b:\n    orig: [x]\n',
        encoding='utf-8',
    )
    with pytest.raises(DuplicateOrigHeaderError):
        HeaderMapping.load(path)
