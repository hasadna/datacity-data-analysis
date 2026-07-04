import dataflows as DF

from lamas.headers.fix_years import fix_years


def run_fix_years(rows):
    return list(DF.Flow(rows, DF.set_type('value', type='any'), DF.validate(), fix_years()).results()[0][0])


def test_strips_bare_year_and_sets_min_year():
    # An embedded year <= the row's own year becomes the new row['year'] (not just a cap) -
    # this is the original process_headers.py behavior, preserved as-is.
    rows = [{'year': 2016, 'header': 'משהו 2015 אחר', 'value': '1', 'name': 'x', 'filename': 'f'}]
    out = run_fix_years(rows)
    assert out[0]['header'] == 'משהו אחר'
    assert out[0]['min_year'] == 2015
    assert out[0]['year'] == 2015


def test_year_never_exceeds_row_year():
    rows = [{'year': 2010, 'header': 'תחזית 2099', 'value': '1', 'name': 'x', 'filename': 'f'}]
    out = run_fix_years(rows)
    assert out[0]['year'] == 2010


def test_1990_is_never_treated_as_an_embedded_year():
    rows = [{'year': 2016, 'header': 'סעיף 1990 בתקנון', 'value': '1', 'name': 'x', 'filename': 'f'}]
    out = run_fix_years(rows)
    assert out[0]['min_year'] is None


def test_strips_month_name_alongside_year():
    # "as of <month> <year>" qualifiers (e.g. "(מאי 2000)") are common in construction/housing
    # headers across many years - stripping only the year left a dangling month name and empty
    # parens, fragmenting what should be the identical header across years.
    rows = [
        {'year': 2000, 'header': 'מספר דירות למגורים לפי חיובי ארנונה (מאי 2000)', 'value': '1', 'name': 'x', 'filename': 'f'},
        {'year': 2008, 'header': 'מספר דירות למגורים לפי חיובי ארנונה (יוני 2008)', 'value': '1', 'name': 'x', 'filename': 'f'},
    ]
    out = run_fix_years(rows)
    assert out[0]['header'] == out[1]['header'] == 'מספר דירות למגורים לפי חיובי ארנונה'


def test_strips_short_year_range_dash_format():
    # 'YYYY-YY' (e.g. a council term "2024-25") is a real CBS format distinct from the full
    # 'YYYY-YYYY'/'YYYY/YY' patterns - without a dedicated regex, bare YEAR matches just "2024"
    # and leaves a dangling "-25" behind, which trailing .strip('/- ') then reduces to a stray
    # "25/" prefix on the header (found for real in 2023/2024 council-member-count data).
    rows = [{'year': 2023, 'header': '2024-25/מספר חברי מועצה', 'value': '1', 'name': 'x', 'filename': 'f'}]
    out = run_fix_years(rows)
    assert out[0]['header'] == 'מספר חברי מועצה'
