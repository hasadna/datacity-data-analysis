import logging
import os
import shutil

import requests

logger = logging.getLogger(__name__)

BASE_URL = 'https://www.cbs.gov.il/he/publications/doclib/2019/hamakomiot1999_2017/'
DOWNLOADS_DIR = 'downloads'
MIN_YEAR = 1999
MAX_YEAR = 2024
XLSX_YEAR = 2016

# CBS serves some years under an irregular filename. Verified empirically via HTTP HEAD
# requests on 2026-07-03: the "plain" `{year}.xlsx` pattern returns a 2056-byte placeholder
# (not a real workbook) for these years; the real file lives at one of the patterns below.
P_LIBUD = {2022, 2023, 2024}   # -> p_libud_{2-digit year}.xlsx
P_LIBUD2 = {2021}              # -> p_libud_{4-digit year}.xlsx


# (connect timeout, read timeout) in seconds - without this, a slow/unresponsive connection to
# CBS's site can hang a download indefinitely (found for real: a CI run stalled 7+ minutes on a
# single request with no timeout set at all).
REQUEST_TIMEOUT = (10, 60)


def download_excel(year, downloads_dir=DOWNLOADS_DIR):
    out_filename = f'{year}' + ('.xlsx' if year >= XLSX_YEAR else '.xls')
    if year in P_LIBUD:
        filename = f'p_libud_{year % 1000}.xlsx'
    elif year in P_LIBUD2:
        filename = f'p_libud_{year}.xlsx'
    else:
        filename = out_filename
    url = BASE_URL + filename
    out_filename = f'{downloads_dir}/lamas-muni-{out_filename}'
    if not os.path.exists(out_filename):
        logger.info('Downloading %s -> %s', url, out_filename)
        r = requests.get(url, stream=True, timeout=REQUEST_TIMEOUT)
        assert r.status_code == 200, f'Failed to download {url}'
        with open(out_filename, 'wb') as f:
            shutil.copyfileobj(r.raw, f)
        del r
    return out_filename


def download_all(downloads_dir=DOWNLOADS_DIR, min_year=MIN_YEAR, max_year=MAX_YEAR):
    """Downloads every configured year, isolated per-year: one year timing out or failing
    (network hiccup, a URL pattern change) is logged and skipped rather than aborting the whole
    batch, so as many years as possible are still available afterward."""
    os.makedirs(downloads_dir, exist_ok=True)
    filenames = {}
    for year in range(min_year, max_year + 1):
        try:
            filenames[year] = download_excel(year, downloads_dir)
        except Exception as e:
            logger.error('Failed to download year %s: %s', year, e)
    return filenames
