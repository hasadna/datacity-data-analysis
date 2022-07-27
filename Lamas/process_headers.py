from collections import Counter
from struct import pack
import dataflows as DF
import re
from decimal import Decimal

from fuzzywuzzy import fuzz

from dataflows_airtable import load_from_airtable

YEAR = re.compile(r'[12]\d{3}')
YEAR_EXT = re.compile(r'[12]\d{3}/\d\d')
YEAR_RANGE = re.compile(r'[12]\d{3}\s*[-/]\s*[12]\d{3}')
HEBYEAR = re.compile('תש["״][א-ת]|תש[א-ת]["״][א-ת]')
DIGITS = re.compile('([0-9-]{2,})')
MULTI_WS = re.compile('\s+')

def fix_years():

    hebyears = set()

    def func(row):
        headers = row['header']
        year = str(row['year'])
        hebyears.update(HEBYEAR.findall(headers))
        headers = HEBYEAR.sub('', headers)
        years = []
        for regexp in (YEAR_RANGE, YEAR_EXT, YEAR):
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
            headers = headers.replace(max_year, '')
            headers = headers.replace(min_year, '')
            for year in years:
                headers = headers.replace(year, '')
            headers = MULTI_WS.sub(' ', headers).strip()
            headers = headers.strip('/- ')
            headers = headers.replace(' /', '/')
            headers = headers.replace(' /', '/')
            headers = headers.replace('//', '/')
            headers = headers.replace('//', '/')
            assert headers != 'חינוך והשכלה/גיל 6', repr(row['header'])
            row['header'] = headers

    return DF.Flow(
        DF.add_field('min_year', 'integer'),
        func,
        DF.finalizer(callback=lambda: print('ALL HEB YEARS', hebyears)),
    )


def translate_headers(headers, translations):
    headers_counter = Counter(headers)
    headers = [x[0] for x in headers_counter.most_common()]
    headers_map = dict()
    missing = set()

    print('# HEADERS', len(headers))
    for i in range(len(headers)):
        if i % 100 == 0:
            print(i, 'headers')
        # msg = None
        for j in range(i + 1, len(headers)):
            if headers[j] in headers_map:
                continue
            ii = headers[i]
            jj = headers[j]
            ii = DIGITS.sub(r'\1\1\1\1\1', ii)
            jj = DIGITS.sub(r'\1\1\1\1\1', jj)
            if fuzz.ratio(ii, jj) > 95:
                headers_map[headers[j]] = headers[i]
        #                 msg = f'{headers[j]} -> {headers[i]}'
        # if msg:
        #     print(msg)
    print('HEADERS MAP', len(headers_map))

    def func(row):
        h = row['header']
        row['orig_header'] = h
        if h in translations:
            row['header'] = translations[h]
        else:
            if h not in missing:
                print('FOUND MISSING TRANSLATION', h)
                missing.add(h)
            row['header'] = headers_map.get(h, h)
        return row
    return DF.Flow(
        func,
        DF.set_type('header', type='string'),
    )

# def ppp1(iterator):
#     for i, row in enumerate(iterator):
#         if i % 100000 == 0:
#             print(i, 'rows')
#         yield row

# def ppp(package: DF.PackageWrapper):
#     print('ppp',package.pkg.descriptor)
#     yield package.pkg
#     # print('ppp', row)
#     for res in package:
#         # data = list(res)
#         # for r in data[:5]:
#         #     print('ppp-r', r)
#         yield ppp1(res)


def specific_fixes():
    def func(rows):
        for row in rows:
            name = row['name']
            header = row['header']
            value = row['value']
            year = row['year']
            if name == 'נוף הגליל' and year < 2001:
                continue
            if name == 'תל אביב -יפו':
                row['name'] = 'תל אביב-יפו'
            yield row
    return func


def value_fixes():
    def func(rows):
        for row in rows:
            name = row['name']
            header = row['header']
            value = row['value']
            year = row['year']
            if value:
                try:
                    value = Decimal(value)
                    if header == 'סה"כ אוכלוסייה (אלפים)':
                        value *= 1000
                        row['header'] = 'סה"כ אוכלוסייה'
                        row['value'] = str(value)
                except:
                    pass
            yield row
    return func


def process_headers(data):
    # data = list(data)
    # print('LLL', len(data))
    # print(data[:4])
    data = DF.Flow(
        data,
        # ppp,
        DF.set_type('value', type='any'),
        DF.validate(),
        fix_years(),
    ).results()[0][0]

    translations = DF.Flow(
        load_from_airtable('apptGe94qTaLjk5Fr', 'Header Mapping', 'Grid view', 'env://AIRTABLE_API_KEY'),
        # DF.printer(),
    ).results()[0][0]
    print(f'GOT {len(translations)} translations')
    translations = dict(
        (x['orig_header'].strip(), x['header'].strip()) for x in translations
    )

    headers = [i['header'] for i in data]
    return DF.Flow(
        data,
        specific_fixes(),
        # ppp,
        translate_headers(headers, translations),
    )
