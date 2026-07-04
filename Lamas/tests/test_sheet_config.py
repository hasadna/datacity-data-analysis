from lamas.sheet_config import Config, SheetConfig


def test_round_trip(tmp_path):
    path = tmp_path / 'sheet_config.yaml'
    sc = SheetConfig(Config(), {}, path)
    sc.set_sheet(2023, 'נתוני תקציב', header_rows=3, extend_headers_top=1)
    sc.save(path)

    sc2 = SheetConfig.load(path)
    cfg = sc2.get(2023, 'נתוני תקציב')
    assert cfg.header_rows == 3
    assert cfg.extend_headers_top == 1
    assert cfg.skip is False


def test_default_when_no_override(tmp_path):
    path = tmp_path / 'sheet_config.yaml'
    sc = SheetConfig(Config(), {}, path)
    assert sc.get(1999, 'anything') == Config()


def test_only_overrides_are_persisted(tmp_path):
    path = tmp_path / 'sheet_config.yaml'
    sc = SheetConfig(Config(), {}, path)
    sc.set_sheet(2021, 'some sheet', skip=True)
    sc.save(path)
    text = path.read_text(encoding='utf-8')
    assert 'skip: true' in text
    assert 'header_rows' not in text.split('some sheet')[1].split('\n')[1]


def test_matches_known_repo_values():
    sc = SheetConfig.load()
    assert sc.get(2016, 'נתוני תקציב').header_rows == 4
    assert sc.get(2016, 'נתוני תקציב').extend_headers_top == 2
    assert sc.get(2021, 'נתוני הסקר החברתי').skip is True
    assert sc.get(2000, 'עיריות ומועצות מקומיות').skip is True
    assert sc.get(2010, 'anything') == Config()
