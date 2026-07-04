from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parent.parent / 'data' / 'sheet_config.yaml'


@dataclass
class Config:
    header_rows: int = 1
    extend_headers_top: int = 0
    extend_headers_bottom: int = 0
    skip: bool = False


class SheetConfig:
    def __init__(self, defaults: Config, years: dict, path: Path):
        self.defaults = defaults
        self.years = years  # {year: {sheet_name: Config}}
        self.path = Path(path)

    @classmethod
    def load(cls, path=DEFAULT_PATH) -> 'SheetConfig':
        path = Path(path)
        if not path.exists():
            return cls(Config(), {}, path)
        raw = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        defaults = Config(**(raw.get('defaults') or {}))
        years = {}
        for year, sheets in (raw.get('years') or {}).items():
            years[int(year)] = {
                sheet: Config(**{**asdict(defaults), **(overrides or {})})
                for sheet, overrides in (sheets or {}).items()
            }
        return cls(defaults, years, path)

    def get(self, year: int, sheet: str) -> Config:
        return self.years.get(year, {}).get(sheet, self.defaults)

    def set_sheet(self, year: int, sheet: str, **overrides) -> None:
        current = asdict(self.get(year, sheet))
        current.update({k: v for k, v in overrides.items() if v is not None})
        self.years.setdefault(year, {})[sheet] = Config(**current)

    def save(self, path=None) -> None:
        path = Path(path or self.path)
        default_dict = asdict(self.defaults)
        out = {
            'version': 1,
            'defaults': default_dict,
            'years': {
                year: {
                    sheet: {
                        k: v for k, v in asdict(cfg).items()
                        if v != default_dict[k]
                    }
                    for sheet, cfg in sorted(sheets.items())
                }
                for year, sheets in sorted(self.years.items())
            },
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(out, allow_unicode=True, sort_keys=False, default_flow_style=False),
            encoding='utf-8',
        )
