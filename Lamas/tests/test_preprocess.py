from lamas.preprocess import fix_value


def test_strips_bidi_control_characters_around_numbers():
    # Excel wraps numbers in invisible RTL-embedding/pop-directional-formatting control
    # characters in Hebrew (RTL) sheets - found for real, flagged as "BAD FLOATS" because
    # float() can't parse a string containing them even though the visible digits are fine.
    bad_floats = set()
    assert fix_value('‫22.9‬', bad_floats) == '22.9'
    assert fix_value('‫5.5 ‬', bad_floats) == '5.5'
    assert bad_floats == set()


def test_dot_space_dot_treated_as_null():
    # A stray malformed null-sentinel found in the raw data (likely meant to be '..').
    bad_floats = set()
    assert fix_value('. .', bad_floats) is None
    assert bad_floats == set()


def test_ordinary_sentinels_still_null():
    bad_floats = set()
    for v in ('-', '..', '', '.', None):
        assert fix_value(v, bad_floats) is None
    assert bad_floats == set()


def test_genuinely_unparseable_value_still_flagged():
    bad_floats = set()
    fix_value('=Q94/R94100', bad_floats)
    assert '=Q94/R94100' in bad_floats


def test_hebrew_text_value_passed_through_unchanged():
    bad_floats = set()
    assert fix_value('טקסט כלשהו', bad_floats) == 'טקסט כלשהו'
    assert bad_floats == set()
