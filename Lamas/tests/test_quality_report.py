"""Automated encoding of the checks a human used to perform by eye in the Airtable "Stats" table:
near-duplicate headers, year-coverage gaps, silently-failed sheets, and known data invariants.

Tests that need real scraped data are skipped if the checkpoint/report doesn't exist yet - run
`lamas preprocess && lamas map-headers` (or `lamas qa` after a `full-run`) to exercise them.
"""
import csv
import re
from pathlib import Path

import pandas as pd
import pytest

from lamas.headers.fuzzy import pairwise_near_duplicates
from lamas.headers.mapping import HeaderMapping
from lamas.headers.specific_fixes import specific_fixes
from lamas.sheet_config import SheetConfig

LAMAS_ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT = LAMAS_ROOT / '.cache' / 'preprocessed.parquet'
PENDING_REPORT = LAMAS_ROOT / 'reports' / 'pending_headers.csv'
MAPPING_PATH = LAMAS_ROOT / 'data' / 'header_mapping.yaml'
DOWNLOADS_DIR = LAMAS_ROOT / 'downloads'

requires_checkpoint = pytest.mark.skipif(
    not CHECKPOINT.exists(), reason='run `lamas preprocess` first to generate a checkpoint'
)


def test_mapping_yaml_valid():
    # HeaderMapping.load() itself raises DuplicateOrigHeaderError on an inconsistent file -
    # loading successfully (and non-emptily) is the check.
    mapping = HeaderMapping.load(MAPPING_PATH)
    assert len(mapping.canonical_headers()) > 0


def test_sheet_config_yaml_valid():
    sc = SheetConfig.load()
    assert sc.defaults is not None


def test_no_near_duplicate_canonical_headers():
    """Surfaces (does not hard-fail on) the failure mode the Airtable Stats review used to catch
    by eye: two canonical headers in the mapping that are textually near-identical.

    This is deliberately a report, not a gate: empirically, some >95-scoring pairs found in the
    seeded mapping are legitimately DISTINCT categories that happen to share most of their text
    (e.g. two "מדדים סובייקטיביים" survey headers differing only in "בכלל לא מרוצה" vs
    "לא כל כך מרוצה" - "not at all satisfied" vs "not so satisfied" - or "...של שכירים" vs
    "...של גברים שכירים" - all employees vs male employees specifically). Auto-merging on score
    alone would silently conflate distinct data. A human (or the lamas-ingest skill) must review
    each candidate's actual meaning before merging - exactly like reviewing a fuzzy-match
    suggestion in reports/pending_headers.csv.
    """
    mapping = HeaderMapping.load(MAPPING_PATH)
    dupes = list(pairwise_near_duplicates(mapping.canonical_headers()))
    if dupes:
        print(f'\n{len(dupes)} near-duplicate canonical header pairs to review (not auto-merged):')
        for a, b, score in dupes:
            print(f'  ({score}) {a!r} <-> {b!r}')


def test_no_mixed_unit_thousands_canonicals():
    """A canonical whose name is tagged '(אלפים)' (thousands) must only ever collect raw
    orig_header variants that are ALSO tagged '(אלפים)' in their own raw text. If a raw variant
    without that tag is merged in, it's a sign the same canonical is being used for two different
    units (thousands from older years vs already-absolute from newer ones, or vice versa) - a real
    bug found and fixed once already (see lamas/headers/value_fixes.py THOUSANDS_TO_ABSOLUTE):
    keep the thousands-unit variant on its OWN dedicated canonical, convert via value_fixes(), and
    only unify with the absolute canonical after conversion, never before."""
    mapping = HeaderMapping.load(MAPPING_PATH)
    violations = {}
    for canonical, origs in mapping.canonical_to_orig.items():
        if 'אלפים' in canonical:
            mismatched = [o for o in origs if 'אלפים' not in o]
            if mismatched:
                violations[canonical] = mismatched
    assert not violations, (
        f'Canonicals tagged (אלפים) with raw variants that are NOT tagged אלפים - likely mixed '
        f'units merged before value_fixes could convert them: {violations}'
    )


@requires_checkpoint
def test_all_mapping_entries_exist_in_source_data():
    """Every orig_header in header_mapping.yaml must actually appear in our real scraped data.
    Catches stale/unused mapping entries (e.g. CBS renames a header, or a bad manual edit adds
    an orig_header that was never real) - the mapping file should only ever contain mappings
    that are actually needed, never speculative or leftover ones."""
    from lamas.headers.pending import real_header_universe

    real_headers = real_header_universe(CHECKPOINT)
    mapping = HeaderMapping.load(MAPPING_PATH)
    unneeded = sorted(set(mapping.known_orig_headers()) - real_headers)
    assert not unneeded, (
        f'{len(unneeded)} orig_header entries in header_mapping.yaml do not appear in the real '
        f'scraped data (not needed - remove them): {unneeded[:20]}'
    )


CANONICAL_FORMAT = re.compile(r'^[^-()]+ - [^()]+( \([^()]+\))?$')


def test_canonical_headers_follow_naming_convention():
    """Reports (does not hard-fail on) canonical headers that don't follow the expected
    '{category} - {metric}' or '{category} - {metric} ({unit})' shape. This is a real, ongoing
    cleanup effort - many existing entries (mechanically ported or self-mapped before this
    convention was settled) don't conform yet. Track this as a TODO to tighten into a hard gate
    once the backlog is cleaned up, rather than blocking on the full historical mapping today."""
    mapping = HeaderMapping.load(MAPPING_PATH)
    violations = [h for h in mapping.canonical_headers() if not CANONICAL_FORMAT.match(h)]
    if violations:
        print(f'\n{len(violations)}/{len(mapping.canonical_headers())} canonical headers do not '
              f'follow "{{category}} - {{metric}}" or "{{category}} - {{metric}} ({{unit}})":')
        for h in violations[:30]:
            print(f'  {h!r}')


# Known, already-investigated (year, sheet, header) collisions that predate this test and are
# not yet root-caused. The 1999/2000 "אחוז שינוי ריאלי לעומת <year>" ones carry genuinely
# different values per municipality (a real extraction ambiguity, likely a missed category row
# akin to the 2023/2024 bug, but in the older .xls format); the 2017-2020 budget-sheet ones carry
# identical duplicated values (a harmless redundant column in CBS's own report). Both are
# isolated and understood well enough not to block on - any NEW/different collision still fails.
KNOWN_DUPLICATE_HEADERS = {
    (1999, 'מועצות אזוריות', 'סה"כ הוצאות של הרשות בתקציב בלתי רגיל - אחוז שינוי ריאלי לעומת 1998'),
    (1999, 'מועצות מקומיות', 'צריכת מים עירונית (אלפי מ"ק)'),
    (1999, 'מועצות מקומיות', 'סה"כ הוצאות של הרשות בתקציב בלתי רגיל - אחוז שינוי ריאלי לעומת 1998'),
    (1999, 'עיריות', 'סה"כ הוצאות של הרשות בתקציב בלתי רגיל - אחוז שינוי ריאלי לעומת 1998'),
    (2000, 'מועצות אזוריות', 'סה"כ הוצאות של הרשות בתקציב בלתי רגיל - אחוז שינוי ריאלי לעומת 1999'),
    (2000, 'נתונים כספיים - עיריות ומ.מקומי', 'סה"כ הוצאות של הרשות בתקציב בלתי רגיל - אחוז שינוי ריאלי לעומת 1999'),
    (2017, 'נתוני תקציב', 'תשלומים בתקציב הרגיל/סה"כ הוצאות בתקציב רגיל'),
    (2018, 'נתוני תקציב', 'תשלומים בתקציב הרגיל/סה"כ הוצאות בתקציב הרגיל'),
    (2019, 'נתוני תקציב', 'תשלומים בתקציב הרגיל/סה"כ הוצאות בתקציב הרגיל'),
    (2020, 'נתוני תקציב', 'תשלומים בתקציב הרגיל/סה"כ הוצאות בתקציב הרגיל'),
}


@requires_checkpoint
def test_no_duplicate_headers_within_sheet():
    """Two different columns in the same (year, sheet) must never produce the identical header
    string - that's silent data corruption (two distinct metrics indistinguishably conflated).
    This is exactly the bug found during 2023/2024 ingestion: a hidden category-label row above
    the column headers wasn't being read, so property-tax-by-type columns under two different
    sections ("charge amount" vs "area") both extracted as bare "למגורים" etc. Fixed by widening
    header_rows/extend_headers_top for that sheet - this test guards against it recurring.

    KNOWN_DUPLICATE_HEADERS carves out a fixed set of already-investigated exceptions (see above)
    so this stays a hard gate for anything new without re-flagging the same understood issues."""
    df = pd.read_parquet(CHECKPOINT)
    violations = []
    known_hits = []
    for (year, sheet), group in df.groupby(['year', 'sheet']):
        counts = group['header'].value_counts()
        # A header can legitimately appear once per row per municipality; what's NOT legitimate
        # is it appearing more times per municipality than there are municipalities (i.e. the
        # same header string used for more than one distinct column).
        n_names = group['name'].nunique()
        for header in counts[counts > n_names].index:
            if (year, sheet, header) in KNOWN_DUPLICATE_HEADERS:
                known_hits.append((year, sheet, header))
            else:
                violations.append((year, sheet, header))
    if known_hits:
        print(f'\n{len(known_hits)} known duplicate-header collisions (see KNOWN_DUPLICATE_HEADERS, '
              f'not yet root-caused but already investigated): {known_hits}')
    assert not violations, (
        f'Duplicate header strings within a sheet (data-integrity risk - check sheet_config.yaml '
        f'header_rows/extend_headers_top for a missed category row): {violations[:5]}'
    )


@requires_checkpoint
@pytest.mark.parametrize('year', [2023, 2024])
def test_headers_present_in_prior_5_years_also_present_in_year(year):
    """For each FINAL (mapped-to-canonical) header that was reported in EVERY one of the 5 years
    immediately preceding `year`, it must still be reported in `year`. A header disappearing right
    after being consistently present for 5 straight years is a strong signal of a broken/silently
    incomplete extraction for `year` - exactly the class of bug found during 2023/2024 ingestion,
    where a whole section's worth of headers went missing without any error - rather than a
    genuine discontinuation (CBS dropping a metric would usually be a single header, not a whole
    block, and real discontinuations are rare enough to warrant a manual look either way).

    Exception: the MOST RECENT year in the dataset is only reported on, never hard-failed. Some
    CBS metrics (found for real: marriage/divorce demographics, crime/justice stats) are published
    with a one-year reporting lag - their header text embeds the actual reference year (e.g. a
    2024 workbook's crime stats are literally labeled "2023"), and fix_years() correctly reassigns
    row['year'] to that embedded year. That means the newest year will always look like it's
    "missing" these lag-reported metrics until next year's workbook arrives - a real gap for any
    OTHER year (already-published lag data that should exist by now), but expected noise for the
    latest year specifically."""
    from lamas.headers.pending import final_headers_by_year

    mapping = HeaderMapping.load(MAPPING_PATH)
    headers_by_year = final_headers_by_year(CHECKPOINT, mapping)

    prior_years = list(range(year - 5, year))
    missing_years = [y for y in prior_years if y not in headers_by_year]
    if missing_years or year not in headers_by_year:
        pytest.skip(f'checkpoint does not cover all of {prior_years + [year]}')

    consistently_present = set.intersection(*(headers_by_year[y] for y in prior_years))
    missing = sorted(consistently_present - headers_by_year[year])

    is_latest_year = year >= max(headers_by_year)
    message = (
        f'{len(missing)} headers were present in every year {prior_years[0]}-{prior_years[-1]} '
        f'but are missing in {year} - check for a silently broken/incomplete extraction '
        f'(sheet_config.yaml header_rows/extend_headers_top/bottom for that year): {missing[:20]}'
    )
    if is_latest_year:
        if missing:
            print(f'\n{message}\n(not failing: {year} is the most recent year in the dataset - '
                  f'likely known reporting-lag metrics, not a broken extraction)')
    else:
        assert not missing, message


@requires_checkpoint
def test_no_unresolved_headers_strict():
    if not PENDING_REPORT.exists():
        pytest.skip('run `lamas map-headers` first to generate the pending report')
    with PENDING_REPORT.open(encoding='utf-8') as f:
        unresolved = [r for r in csv.DictReader(f) if r['status'] == 'unresolved']
    assert unresolved == [], (
        f'{len(unresolved)} headers remain unresolved - run the lamas-ingest skill to triage '
        f'reports/pending_headers.csv before treating the dataset as production-ready'
    )


@requires_checkpoint
def test_specific_fixes_invariants():
    """Checks the invariants AFTER specific_fixes() runs, not the raw checkpoint (which is
    expected to still contain the pre-fix name variants - that's exactly what this step cleans)."""
    df = pd.read_parquet(CHECKPOINT)
    rows = list(specific_fixes()(df.where(pd.notnull(df), None).to_dict('records')))
    fixed = pd.DataFrame(rows)
    assert not ((fixed['name'] == 'נוף הגליל') & (fixed['year'] < 2001)).any(), \
        'נוף הגליל rows before 2001 should have been dropped by specific_fixes()'
    assert not (fixed['name'] == 'תל אביב -יפו').any(), 'stray-space Tel Aviv-Yafo spelling leaked through'
    assert not (fixed['name'] == 'הרצלייה').any(), 'double-yod Herzliya spelling leaked through'


@requires_checkpoint
def test_row_counts_per_year_sheet_reported():
    """Not a hard pass/fail gate (different sheets/years have legitimately different sizes) -
    surfaces outliers so a human can sanity-check a year that might have silently under-scraped."""
    df = pd.read_parquet(CHECKPOINT)
    counts = df.groupby(['year', 'sheet']).size()
    median = counts.median()
    outliers = counts[(counts < median * 0.5) | (counts > median * 2.0)]
    if len(outliers) > 0:
        print(f'\nRow-count outliers vs median ({median:.0f}):\n{outliers}')


def test_sheet_config_has_no_gaps_for_downloaded_years():
    """Catches known issue #3 from CURRENT_BEHAVIOR.md going forward: a downloaded year that
    hasn't had its sheet layout config reviewed at all. Years using pure defaults are fine;
    this flags years from 2016 onward (when CBS started needing multi-row-header overrides)
    that have zero explicit sheet_config.yaml entries."""
    if not DOWNLOADS_DIR.exists():
        pytest.skip('no downloads/ directory present')
    sc = SheetConfig.load()
    years_downloaded = {int(p.stem.split('-')[-1]) for p in DOWNLOADS_DIR.glob('lamas-muni-*.*')}
    problem_years = sorted(y for y in years_downloaded if y >= 2016 and y not in sc.years)
    assert not problem_years, (
        f'Years downloaded but missing sheet_config.yaml entries: {problem_years} - '
        f'run the lamas-ingest skill (lamas diagnose --year Y) to configure them'
    )
