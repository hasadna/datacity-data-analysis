from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / 'data' / 'header_mapping.yaml'


class DuplicateOrigHeaderError(Exception):
    pass


class HeaderMapping:
    """Canonical header -> list of raw orig_header variants, replacing the Airtable "Header Mapping" table."""

    def __init__(self, canonical_to_orig: dict, path: Path):
        self.canonical_to_orig = canonical_to_orig
        self.path = Path(path)
        self.orig_to_canonical = {}
        self._rebuild_index()

    def _rebuild_index(self):
        index = {}
        for canonical, origs in self.canonical_to_orig.items():
            for orig in origs:
                if orig in index and index[orig] != canonical:
                    raise DuplicateOrigHeaderError(
                        f'{orig!r} maps to both {index[orig]!r} and {canonical!r}'
                    )
                index[orig] = canonical
        self.orig_to_canonical = index

    @classmethod
    def load(cls, path=DEFAULT_PATH) -> 'HeaderMapping':
        path = Path(path)
        if not path.exists():
            return cls({}, path)
        raw = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        canonical_to_orig = {
            canonical: list(dict.fromkeys((entry or {}).get('orig') or []))
            for canonical, entry in (raw.get('headers') or {}).items()
        }
        return cls(canonical_to_orig, path)

    def save(self, path=None) -> None:
        path = Path(path or self.path)
        out = {
            'version': 1,
            'headers': {
                canonical: {'orig': sorted(origs)}
                for canonical, origs in sorted(self.canonical_to_orig.items())
            },
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(out, allow_unicode=True, sort_keys=False, default_flow_style=False),
            encoding='utf-8',
        )

    def resolve(self, orig_header):
        return self.orig_to_canonical.get(orig_header)

    def add_mapping(self, canonical, orig_header):
        existing = self.orig_to_canonical.get(orig_header)
        if existing is not None and existing != canonical:
            raise DuplicateOrigHeaderError(
                f'{orig_header!r} is already mapped to {existing!r}, not {canonical!r}'
            )
        origs = self.canonical_to_orig.setdefault(canonical, [])
        if orig_header not in origs:
            origs.append(orig_header)
        self.orig_to_canonical[orig_header] = canonical

    def known_orig_headers(self):
        return list(self.orig_to_canonical.keys())

    def canonical_headers(self):
        return list(self.canonical_to_orig.keys())
