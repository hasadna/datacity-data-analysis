from lamas.headers.specific_fixes import specific_fixes


def test_drops_nof_hagalil_pre_2001():
    rows = [
        {'name': 'נוף הגליל', 'year': 2000, 'header': 'h', 'value': '1'},
        {'name': 'נוף הגליל', 'year': 2001, 'header': 'h', 'value': '1'},
    ]
    out = list(specific_fixes()(rows))
    assert len(out) == 1
    assert out[0]['year'] == 2001


def test_fixes_name_typos():
    rows = [
        {'name': 'תל אביב -יפו', 'year': 2010, 'header': 'h', 'value': '1'},
        {'name': 'הרצלייה', 'year': 2010, 'header': 'h', 'value': '1'},
    ]
    out = list(specific_fixes()(rows))
    assert out[0]['name'] == 'תל אביב-יפו'
    assert out[1]['name'] == 'הרצליה'


def test_unrelated_names_untouched():
    rows = [{'name': 'ירושלים', 'year': 2010, 'header': 'h', 'value': '1'}]
    out = list(specific_fixes()(rows))
    assert out[0]['name'] == 'ירושלים'
