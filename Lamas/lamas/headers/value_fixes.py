import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

# Canonical headers that represent a metric "in thousands" and need converting (x1000) onto the
# equivalent absolute canonical. The original process_headers.py matched 3 hardcoded flat strings
# (e.g. 'סה"כ אוכלוסייה (אלפים)') - that broke once header_mapping.yaml's canonicals started
# carrying category prefixes (e.g. 'דמוגרפיה - סה"כ אוכלוסייה (אלפים)'), since the exact-string
# match could never fire again. It also can't be fixed with a suffix-only match: the "(אלפים)" and
# already-absolute raw variants for the same metric were, at one point, merged into a single
# canonical BEFORE value_fixes ran - which erases the information needed to convert only the
# thousands-sourced rows. The fix has two parts: (1) header_mapping.yaml must keep a
# thousands-unit raw variant on its OWN dedicated canonical, never merged with an already-absolute
# variant of the same metric; (2) this table converts+renames each dedicated thousands canonical
# onto its already-established absolute counterpart.
THOUSANDS_TO_ABSOLUTE = {
    'דמוגרפיה - סה"כ אוכלוסייה (אלפים)': 'דמוגרפיה - אוכלוסייה (סה"כ)',
    'דמוגרפיה - סה"כ גברים (אלפים)': 'דמוגרפיה - גברים (סה"כ)',
    'דמוגרפיה - סה"כ נשים (אלפים)': 'דמוגרפיה - נשים (סה"כ)',
    'שימושי קרקע - סה"כ אוכלוסייה (אלפים)': 'שימושי קרקע - אוכלוסייה (סה"כ)',
    'שימושי קרקע - אוכלוסייה סוף סך הכל אלפים': 'שימושי קרקע - אוכלוסייה סוף סך הכל (סה"כ)',
}


def value_fixes():
    """Unit conversions: thousands -> absolute (via THOUSANDS_TO_ABSOLUTE), m^2 -> thousands of m^2."""

    def func(rows):
        for row in rows:
            header = row['header']
            value = row['value']
            if value:
                try:
                    value = Decimal(value)
                    if header in THOUSANDS_TO_ABSOLUTE:
                        value *= 1000
                        row['header'] = THOUSANDS_TO_ABSOLUTE[header]
                        row['value'] = str(value)
                    if header.endswith('(שטח במ"ר)'):
                        value /= 1000
                        row['header'] = header.replace('(שטח במ"ר)', '(שטח באלפי מ"ר)')
                        row['value'] = str(value)
                    # TODO: merge 'גמר של סלילת כבישים חדשים' and
                    # 'גמר של הרחבה ושיקום של כבישים חדשים' (and their 'התחלה...' counterparts)
                    # into a single combined header - carried over from the original
                    # process_headers.py, never implemented there either.
                except Exception:
                    logger.debug('value_fixes: could not parse %r as Decimal for header %r', row['value'], header)
            yield row
    return func
