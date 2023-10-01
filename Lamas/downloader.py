import os
import requests
import shutil

BASE_URL = 'https://www.cbs.gov.il/he/publications/doclib/2019/hamakomiot1999_2017/'
DOWNLOADS_DIR = 'downloads'
MIN_YEAR = 1999
MAX_YEAR = 2021
XLSX_YEAR = 2016
P_LIBUD = {2021}


def download_excel(year):
    out_filename = f'{year}' + ('.xlsx' if year >= XLSX_YEAR else '.xls')
    if year in P_LIBUD:
        filename = f'p_libud_{year % 1000}.xlsx'
    else:
        filename = out_filename
    url = BASE_URL + filename
    out_filename = f'{DOWNLOADS_DIR}/lamas-muni-{out_filename}'
    if not os.path.exists(filename):
        r = requests.get(url, stream=True)
        assert r.status_code == 200, f'Failed to download {url}'
        with open(out_filename, 'wb') as f:
            shutil.copyfileobj(r.raw, f)
        del r
    return out_filename

def download_all():
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    return dict(
        (year, download_excel(year))
        for year in range(MIN_YEAR, MAX_YEAR + 1)
    )
