from decimal import Decimal

from lamas.headers.value_fixes import value_fixes


def test_population_thousands_converted_onto_absolute_canonical():
    # Regression test: the canonical must include its real category prefix (this is what
    # header_mapping.yaml actually produces) - an exact-match-only check silently stops firing
    # the moment a prefix is introduced, which is exactly the bug this table-driven approach fixes.
    rows = [{'header': 'דמוגרפיה - סה"כ אוכלוסייה (אלפים)', 'value': '12.5', 'name': 'x', 'year': 2020}]
    out = list(value_fixes()(rows))
    assert out[0]['header'] == 'דמוגרפיה - אוכלוסייה (סה"כ)'
    assert Decimal(out[0]['value']) == Decimal('12500')


def test_men_and_women_thousands_converted_onto_absolute_canonical():
    rows = [
        {'header': 'דמוגרפיה - סה"כ גברים (אלפים)', 'value': '1', 'name': 'x', 'year': 2020},
        {'header': 'דמוגרפיה - סה"כ נשים (אלפים)', 'value': '1', 'name': 'x', 'year': 2020},
    ]
    out = list(value_fixes()(rows))
    assert out[0]['header'] == 'דמוגרפיה - גברים (סה"כ)'
    assert out[1]['header'] == 'דמוגרפיה - נשים (סה"כ)'
    assert Decimal(out[0]['value']) == Decimal('1000')


def test_already_absolute_population_left_untouched():
    # An already-absolute row must never be re-multiplied by 1000 - this is exactly why the
    # thousands-unit raw variant must stay on its own dedicated canonical, never merged with an
    # already-absolute variant before value_fixes runs.
    rows = [{'header': 'דמוגרפיה - אוכלוסייה (סה"כ)', 'value': '981711', 'name': 'x', 'year': 2022}]
    out = list(value_fixes()(rows))
    assert out[0]['header'] == 'דמוגרפיה - אוכלוסייה (סה"כ)'
    assert Decimal(out[0]['value']) == Decimal('981711')


def test_area_thousands_converted():
    rows = [{'header': 'משהו (שטח במ"ר)', 'value': '5000', 'name': 'x', 'year': 2020}]
    out = list(value_fixes()(rows))
    assert out[0]['header'] == 'משהו (שטח באלפי מ"ר)'
    assert Decimal(out[0]['value']) == Decimal('5')


def test_non_numeric_value_untouched():
    rows = [{'header': 'משהו', 'value': 'לא ידוע', 'name': 'x', 'year': 2020}]
    out = list(value_fixes()(rows))
    assert out[0]['value'] == 'לא ידוע'


def test_empty_value_untouched():
    rows = [{'header': 'דמוגרפיה - סה"כ אוכלוסייה (אלפים)', 'value': None, 'name': 'x', 'year': 2020}]
    out = list(value_fixes()(rows))
    assert out[0]['value'] is None
