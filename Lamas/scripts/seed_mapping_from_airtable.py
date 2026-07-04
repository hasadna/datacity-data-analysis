"""One-time migration helper: seed data/header_mapping.yaml from the LIVE Airtable "Header
Mapping" table (base apptGe94qTaLjk5Fr) - the table `process_headers.py` used to read on every
run before this modernization. That table represents years of actual human curation and is a far
better seed than any local snapshot; use it as the primary source. Not part of the standing
pipeline - run once, review the "NOT COVERED" report it prints, then commit header_mapping.yaml.

Every candidate orig_header is still cross-referenced against the REAL set of headers actually
produced by preprocessing our own downloaded workbooks (post fix_years) - this is the sole filter
against unrelated content Airtable's base might also contain (it's shared across several CBS
report types beyond this muni pipeline). No heuristic auto-resolution happens here for headers
NOT covered by Airtable - those are reported so they can be handled one by one (tight heuristic or
human approval), never bulk-guessed.

Usage: python scripts/seed_mapping_from_airtable.py [--checkpoint PATH]
  --checkpoint: a parquet file produced by `lamas preprocess` (defaults to the standard cache
                path). Run `lamas preprocess` first if it doesn't exist yet.
  Requires AIRTABLE_API_KEY in Lamas/.env and the `dataflows-airtable` dev dependency installed.
"""
import argparse
import sys
from pathlib import Path

import dataflows as DF
import dotenv

LAMAS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAMAS_ROOT))

from lamas.headers.mapping import DuplicateOrigHeaderError, HeaderMapping  # noqa: E402
from lamas.headers.pending import real_header_universe  # noqa: E402

OUTPUT_PATH = LAMAS_ROOT / 'data' / 'header_mapping.yaml'
DEFAULT_CHECKPOINT = LAMAS_ROOT / '.cache' / 'preprocessed.parquet'
AIRTABLE_BASE = 'apptGe94qTaLjk5Fr'
AIRTABLE_TABLE = 'Header Mapping'
AIRTABLE_VIEW = 'Grid view'


def load_airtable_rows():
    dotenv.load_dotenv(str(LAMAS_ROOT / '.env'), override=True)
    from dataflows_airtable import load_from_airtable
    return DF.Flow(
        load_from_airtable(AIRTABLE_BASE, AIRTABLE_TABLE, AIRTABLE_VIEW, 'env://AIRTABLE_API_KEY'),
    ).results()[0][0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkpoint', default=str(DEFAULT_CHECKPOINT))
    args = parser.parse_args()

    checkpoint = Path(args.checkpoint)
    if not checkpoint.exists():
        print(f'{checkpoint} does not exist - run `lamas preprocess` first.', file=sys.stderr)
        sys.exit(1)

    real_headers = real_header_universe(checkpoint)
    print(f'Real header universe: {len(real_headers)} distinct headers')

    airtable_rows = load_airtable_rows()
    print(f'Loaded {len(airtable_rows)} rows from Airtable {AIRTABLE_BASE}/{AIRTABLE_TABLE}')

    mapping = HeaderMapping({}, OUTPUT_PATH)
    added, rejected_not_real, conflicts = 0, 0, 0
    for row in airtable_rows:
        header = (row.get('header') or '').strip()
        orig_header = (row.get('orig_header') or '').strip()
        if not header or not orig_header:
            continue
        if orig_header not in real_headers:
            rejected_not_real += 1
            continue
        try:
            mapping.add_mapping(header, orig_header)
            added += 1
        except DuplicateOrigHeaderError as e:
            conflicts += 1
            print(f'SKIP (conflict): {e}')
    mapping.save(OUTPUT_PATH)

    covered = set(mapping.known_orig_headers())
    uncovered = sorted(real_headers - covered)
    print(
        f'Seeded {len(mapping.canonical_headers())} canonical headers from {added} Airtable rows '
        f'(rejected {rejected_not_real} rows not in the real universe, {conflicts} conflicts) '
        f'-> {OUTPUT_PATH}'
    )
    print(f'\n{len(uncovered)} real headers NOT covered by Airtable - these need one-by-one review, not bulk mapping:')
    for h in uncovered:
        print(f'  {h!r}')


if __name__ == '__main__':
    main()
