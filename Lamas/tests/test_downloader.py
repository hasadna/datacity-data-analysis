import io

from lamas.downloader import REQUEST_TIMEOUT, download_all, download_excel


class FakeResponse:
    def __init__(self):
        self.status_code = 200
        self.raw = io.BytesIO(b'fake-content')


def _patch_get(monkeypatch, calls, kwargs_seen=None):
    def fake_get(url, stream=True, timeout=None):
        calls.append(url)
        if kwargs_seen is not None:
            kwargs_seen.append({'stream': stream, 'timeout': timeout})
        return FakeResponse()
    monkeypatch.setattr('lamas.downloader.requests.get', fake_get)
    monkeypatch.setattr('lamas.downloader.shutil.copyfileobj', lambda *a, **k: None)


def test_download_passes_a_timeout(monkeypatch, tmp_path):
    # A hung/unresponsive connection to CBS's site must not block forever - found for real in
    # CI, where a request with no timeout stalled a run for 7+ minutes.
    calls, kwargs_seen = [], []
    _patch_get(monkeypatch, calls, kwargs_seen)
    download_excel(2020, str(tmp_path))
    assert kwargs_seen[0]['timeout'] == REQUEST_TIMEOUT
    assert kwargs_seen[0]['timeout'] is not None


def test_p_libud_years_use_two_digit_pattern(monkeypatch, tmp_path):
    calls = []
    _patch_get(monkeypatch, calls)
    for year in (2022, 2023, 2024):
        download_excel(year, str(tmp_path))
    assert calls == [
        'https://www.cbs.gov.il/he/publications/doclib/2019/hamakomiot1999_2017/p_libud_22.xlsx',
        'https://www.cbs.gov.il/he/publications/doclib/2019/hamakomiot1999_2017/p_libud_23.xlsx',
        'https://www.cbs.gov.il/he/publications/doclib/2019/hamakomiot1999_2017/p_libud_24.xlsx',
    ]


def test_p_libud2_year_uses_four_digit_pattern(monkeypatch, tmp_path):
    calls = []
    _patch_get(monkeypatch, calls)
    download_excel(2021, str(tmp_path))
    assert calls == [
        'https://www.cbs.gov.il/he/publications/doclib/2019/hamakomiot1999_2017/p_libud_2021.xlsx',
    ]


def test_ordinary_years_use_plain_pattern(monkeypatch, tmp_path):
    calls = []
    _patch_get(monkeypatch, calls)
    download_excel(2020, str(tmp_path))
    download_excel(1999, str(tmp_path))
    assert calls == [
        'https://www.cbs.gov.il/he/publications/doclib/2019/hamakomiot1999_2017/2020.xlsx',
        'https://www.cbs.gov.il/he/publications/doclib/2019/hamakomiot1999_2017/1999.xls',
    ]


def test_skips_download_if_file_already_exists(monkeypatch, tmp_path):
    calls = []
    _patch_get(monkeypatch, calls)
    out = tmp_path / 'lamas-muni-2020.xlsx'
    out.write_bytes(b'already here')
    result = download_excel(2020, str(tmp_path))
    assert calls == []
    assert result == str(out)


def test_download_all_isolates_a_failing_year(monkeypatch, tmp_path):
    # One year timing out or erroring (network hiccup, a URL pattern change) must not abort the
    # whole batch - every other year should still download successfully.
    def flaky_get(url, stream=True, timeout=None):
        if '2021' in url:
            raise TimeoutError('simulated hang')
        return FakeResponse()
    monkeypatch.setattr('lamas.downloader.requests.get', flaky_get)
    monkeypatch.setattr('lamas.downloader.shutil.copyfileobj', lambda *a, **k: None)

    filenames = download_all(str(tmp_path), min_year=2020, max_year=2022)
    assert set(filenames.keys()) == {2020, 2022}
    assert 2021 not in filenames
