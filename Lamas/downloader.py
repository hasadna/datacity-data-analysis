import os
import requests
import shutil

BASE_URL = 'https://www.cbs.gov.il/he/publications/doclib/2019/hamakomiot1999_2017/'
DOWNLOADS_DIR = 'downloads'
MIN_YEAR = 1999
MAX_YEAR = 2020
XLSX_YEAR = 2016


def download_excel(year):
    filename = f'{year}' + ('.xlsx' if year >= XLSX_YEAR else '.xls')
    url = BASE_URL + filename
    filename = f'{DOWNLOADS_DIR}/lamas-muni-{filename}'
    if not os.path.exists(filename):
        r = requests.get(url, stream=True)
        with open(filename, 'wb') as f:
            shutil.copyfileobj(r.raw, f)
        del r
    return filename

def download_all():
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    return dict(
        (year, download_excel(year))
        for year in range(MIN_YEAR, MAX_YEAR + 1)
    )
