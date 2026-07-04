import io

from lamas.downloader import download_excel


class FakeResponse:
    def __init__(self):
        self.status_code = 200
        self.raw = io.BytesIO(b'fake-content')


def _patch_get(monkeypatch, calls):
    def fake_get(url, stream=True):
        calls.append(url)
        return FakeResponse()
    monkeypatch.setattr('lamas.downloader.requests.get', fake_get)
    monkeypatch.setattr('lamas.downloader.shutil.copyfileobj', lambda *a, **k: None)


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
