import logging
import re

import dataflows as DF

logger = logging.getLogger(__name__)

YEAR = re.compile(r'[12]\d{3}')
YEAR_EXT = re.compile(r'[12]\d{3}/\d\d')
YEAR_EXT_DASH = re.compile(r'[12]\d{3}-\d{2}\b')
YEAR_RANGE = re.compile(r'[12]\d{3}\s*[-/]\s*[12]\d{3}')
HEBYEAR = re.compile('תש["״][א-ת]|תש[א-ת]["״][א-ת]')
COMPARE_YEAR = re.compile('לעומת [0-9]{4}')
MULTI_WS = re.compile(r'\s+')
# "as of <month> <year>" data-collection-date qualifiers (e.g. "(מאי 2000)", "יוני 2017/...") are
# common in construction/housing headers across many years - the year gets stripped below, but
# without this the month name is left dangling (e.g. "(מאי )"), fragmenting otherwise-identical
# headers across years. Stripped unconditionally, like HEBYEAR.
MONTH_NAME = re.compile(
    r'\b(ינואר|פברואר|מרץ|אפריל|מאי|יוני|יולי|אוגוסט|ספטמבר|אוקטובר|נובמבר|דצמבר)\b'
)
EMPTY_PARENS = re.compile(r'\(\s*\)')


def fix_years(hebyears_report_path=None):
    """Strip year references embedded in header text, deriving row['year']/row['min_year'].

    `hebyears_report_path`, if given, persists the Hebrew-calendar-year tokens seen (a diagnostic
    that used to be print-only and discarded).
    """
    hebyears = set()

    def func(row):
        headers = row['header']
        year = str(row['year'])
        headers = COMPARE_YEAR.sub('לעומת', headers)
        hebyears.update(HEBYEAR.findall(headers))
        headers = HEBYEAR.sub('', headers)
        month_found = bool(MONTH_NAME.search(headers))
        headers = MONTH_NAME.sub('', headers)
        years = []
        for regexp in (YEAR_RANGE, YEAR_EXT, YEAR_EXT_DASH, YEAR):
            for m in regexp.findall(headers):
                if len(m) == 4:
                    years.append(m)
                if len(m) == 7:
                    years.append(m[:4])
                    years.append('20' + m[5:] if m[5] != '9' else '19' + m[5:])
                if len(m) >= 9:
                    years.extend(YEAR.findall(m))
                headers = headers.replace(m, '')
        if '1990' in years:
            years.remove('1990')
        years = sorted(set(years))
        if len(years) > 0:
            max_year = max(years)
            if max_year > year:
                max_year = year
            min_year = min(years)
            if min_year > max_year:
                min_year = max_year
            row['year'] = int(max_year)
            row['min_year'] = int(min_year)
            headers = YEAR_RANGE.sub('', headers)
            headers = YEAR_EXT.sub('', headers)
            headers = YEAR_EXT_DASH.sub('', headers)
            headers = headers.replace(max_year, '')
            headers = headers.replace(min_year, '')
            for y in years:
                headers = headers.replace(y, '')

        if len(years) > 0 or month_found:
            headers = EMPTY_PARENS.sub('', headers)
            headers = MULTI_WS.sub(' ', headers).strip()
            headers = headers.strip('/- ')
            headers = headers.replace(' /', '/')
            headers = headers.replace(' /', '/')
            headers = headers.replace('//', '/')
            headers = headers.replace('//', '/')

        row['header'] = headers

    def finalize():
        logger.debug('Hebrew calendar year tokens seen: %s', sorted(hebyears))
        if hebyears_report_path:
            hebyears_report_path.parent.mkdir(parents=True, exist_ok=True)
            hebyears_report_path.write_text('\n'.join(sorted(hebyears)), encoding='utf-8')

    return DF.Flow(
        DF.add_field('min_year', 'integer'),
        func,
        DF.finalizer(callback=finalize),
    )
