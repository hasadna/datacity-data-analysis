---
name: lamas-ingest
description: Ingest a newly-published (or previously-failing) Lamas/CBS municipal statistics year end-to-end - download, tune sheet parsing config, resolve header mappings, run QA, and hand off to Postgres. Use when asked to ingest, add, process, or fix a Lamas/CBS year, or when Lamas/reports/pending_headers.csv or sheet_config.yaml has gaps for a downloaded year.
---

# Lamas year ingestion

This skill walks through ingesting one year of the Lamas (Israeli CBS municipal statistics)
pipeline end-to-end. It is orchestration over the `lamas` CLI (installed via `Lamas/pyproject.toml`,
run `pip install -e Lamas/` once if the `lamas` command isn't found) - call CLI commands and make
decisions based on their output; don't reimplement parsing logic yourself.

Background reading if you need it: `Lamas/docs/CURRENT_BEHAVIOR.md` describes the pipeline's
original (pre-modernization) behavior in depth. The two files this skill maintains are
`Lamas/data/sheet_config.yaml` (per-year/per-sheet Excel layout config) and
`Lamas/data/header_mapping.yaml` (canonical header -> raw orig_header variants) - both are the
only state that needs to persist across a session; there should be no other manual notes.

Ask the user which year to ingest if it isn't obvious from context (e.g. "ingest 2023").

## The one non-negotiable rule

**Every unmapped header gets resolved ONE BY ONE, by a tight heuristic or explicit human/AI
semantic review - never in bulk, never by "no better candidate was found = safe to accept."**

This skill previously got this wrong: it bulk-added ~800 unmapped headers as their own new
canonicals just because no fuzzy match existed against the *then-current* mapping. That produced
exactly the fragmentation this whole system exists to prevent - e.g. `כיתות בבתי ספר תיכוניים` and
`כיתות בבתי ספר תיכונים` (a one-letter spelling variant) both became separate canonicals, because
the bulk script only checked for *exact* matches against prior entries, never fuzzy-checked new
candidates *against each other* within the same batch. "I found no reason to reject this" is not
the same as "I confirmed this is correct" - always require the latter. See Step 3 and Step 6 below
for what a real per-header review looks like, including two cases where the same batch's own
fuzzy scores were themselves misleading and had to be overridden.

## Step 0 - Prefer the live Airtable table as your seed, not ad hoc local guessing

If `header_mapping.yaml` looks thin, stale, or you're rebuilding it from scratch, do **not**
hand-roll a seed from local CSV exports or self-mapping heuristics. The live Airtable base
(`apptGe94qTaLjk5Fr`, table `Header Mapping`) represents years of actual human curation and is a
far better starting point than anything you can reconstruct locally:

```
python Lamas/scripts/seed_mapping_from_airtable.py [--checkpoint PATH]
```

Requires `AIRTABLE_API_KEY` in `Lamas/.env` (still present as of this writing) and the
`dataflows-airtable` dev dependency. This script cross-references every Airtable orig_header
against the real header universe from your own preprocessed checkpoint (the only filter needed -
no keyword denylist required, contrary to an earlier assumption; Airtable's table matched >99% of
real headers cleanly). It prints whatever real headers Airtable's table doesn't cover - that
residual is your genuine one-by-one review queue for Step 3/6, not a bulk-fill target.

In one real run, seeding from a stale local CSV snapshot left ~95 headers uncovered *and*
introduced fragmentation; seeding from live Airtable left only ~15 pending, nearly all already
correctly disambiguated. If Airtable access ever stops working, fall back to a local seed only as
a last resort, and treat everything it produces as unverified until reviewed.

## Step 1 - Ensure downloaded

```
lamas download --year <YEAR>
```
Confirm the file lands in `Lamas/downloads/lamas-muni-<YEAR>.xlsx` (or `.xls`). If the download
fails, check `Lamas/lamas/downloader.py`'s `P_LIBUD`/`P_LIBUD2` filename patterns - CBS has used
irregular filenames before (`p_libud_<2-digit-year>.xlsx` or `p_libud_<4-digit-year>.xlsx` instead
of the plain `<year>.xlsx`/`.xls`) and a brand new year might need a new entry added to one of
those sets. You can verify which URL pattern is live with a HEAD request, e.g.:
```
curl -sI https://www.cbs.gov.il/he/publications/doclib/2019/hamakomiot1999_2017/<YEAR>.xlsx
curl -sI https://www.cbs.gov.il/he/publications/doclib/2019/hamakomiot1999_2017/p_libud_<2-digit-year>.xlsx
```
A real workbook responds with `Content-Type: application/vnd.openxmlformats-officedocument...`
and a multi-hundred-KB `Content-Length`; the broken/placeholder response is a ~2056-byte body.

## Step 2 - Ensure it's configured and parses correctly (including hidden multi-row headers)

```
lamas diagnose --year <YEAR>
```
This dry-run-parses every sheet (full header location AND row extraction) against the *current*
`sheet_config.yaml` and reports, per sheet: whether it's configured to skip, the detected header
count and name-column index, a preview of the first ~15 distinct headers, or the exact parse
error (including errors that only occur during row extraction, like a "Total" summary row with no
real municipality name).

For each sheet, decide:
- **Looks right already** (header preview reads as real Hebrew column labels, name column
  detected, no error) - **do not stop here**. A clean-looking preview is not proof the extraction
  is correct - see the "silent duplicate headers" warning below before moving on.
- **Errors out** (`MagicPositionError`, `OrientationError`, `NameColumnError`, `BadHeaderError`,
  `RowExtractionError`) or **produces a suspicious preview** (too few headers, obviously
  mis-joined/truncated fragments, e.g. numbers where Hebrew text should be) - the sheet's layout
  changed and needs a new/updated `sheet_config.yaml` entry. Iterate:
  ```
  lamas config set-sheet --year <YEAR> --sheet "<exact sheet name>" \
      [--header-rows N] [--extend-top N] [--extend-bottom N] [--skip/--no-skip]
  lamas diagnose --year <YEAR> --sheet "<exact sheet name>"
  ```
  Common patterns seen historically (see `CURRENT_BEHAVIOR.md` section 4): CBS periodically adds
  more stacked header rows (`--header-rows`) or needs the header block extended upward
  (`--extend-top`) to pick up a category label sitting one or two rows above the anchor, or
  inserts blank/aggregate rows right after the header block that `--extend-bottom` should skip
  past (found in 2023: a blank row + 4 nationwide/city-type aggregate rows sat between the header
  and the first real municipality row). If a sheet is a genuinely different report (e.g. a
  social/labor-force survey with a fundamentally different shape - repeated/nested municipality
  entries, unit-label sub-rows - matching the historical pattern of `נתוני הסקר החברתי` /
  `סקרי כוח אדם והוצאות משק בית` being skipped in 2021-2022), mark it `--skip` rather than
  fighting the parser.

**Silent duplicate headers - check this even when diagnose looks clean.** A real bug found during
2023/2024 ingestion: the budget sheet has a genuine 2-row header (a category-group row sitting
above the visible column-label row, e.g. `חיובי ארנונה לפי סוג נכס - באלפי ש"ח` grouping ~18
property-type columns, with a parallel `...שטח באלפי מ"ר` group for a completely different
metric). With `header_rows=1`, that group row was invisible, so both groups' `למגורים` column
extracted as the bare, identical string `למגורים` - two different metrics (a currency charge and
an area) silently collided under one header string with no error and a perfectly normal-looking
preview. The fix was `header_rows=2` (reading the category row too), which produced distinct,
correctly-scoped headers for every column. To catch this class of bug:
1. After `lamas preprocess --year <YEAR>`, run `lamas qa` - `test_no_duplicate_headers_within_sheet`
   specifically checks that no header string appears more times per `(year, sheet)` than there are
   distinct municipalities, which is exactly this failure mode.
2. If it's a wide sheet with dozens of similarly-shaped columns (property-type or category
   breakdowns), it's worth eyeballing the raw Excel rows above the header row directly (openpyxl:
   `sheet.rows`, or check `sheet.merged_cells.ranges` - note CBS sheets are often NOT true merged
   cells, just an isolated label in one cell of an otherwise-blank row, so check for stray non-None
   values in the row(s) above the header row even if `merged_cells.ranges` is empty).

Once all sheets are settled, generate a checkpoint including the new year:
```
lamas preprocess --checkpoint Lamas/.cache/preprocessed.parquet
```
(Omit `--year` to refresh the full historical checkpoint so later steps - stats, build - see the
new year alongside all prior years. Use `--year <YEAR>` alone only for a quick iteration loop, but
switch to a full-checkpoint run before Step 3 onward, since `map-headers`/`build` operate against
whatever checkpoint currently exists.)

**If you later change `sheet_config.yaml` after some mappings are already confirmed** (e.g. you
initially diagnosed with `header_rows=1`, confirmed some fuzzy matches, then discovered the hidden
duplicate-header issue and switched to `header_rows=2`): the raw text those earlier mappings were
keyed on no longer gets produced by extraction at all. Find and remove those now-orphaned `orig`
entries from `header_mapping.yaml` (search for the exact old strings) before re-running
`map-headers` - otherwise the file accumulates dead entries that `test_all_mapping_entries_exist_in_source_data`
(see Step 7) will flag anyway, but it's cleaner to catch it immediately.

## Step 3 - Run header mapping, focused on what's new

```
lamas map-headers --year <YEAR>
```
This regenerates `Lamas/reports/pending_headers.csv`, scoped to the year being ingested. Sort by
`count` descending and go through **every row individually** - see Step 6 for concrete review
techniques. Never batch-accept a whole status group.

- **`status == auto_resolved_needs_confirmation`** (a fuzzy match above the auto-merge threshold
  already exists and was applied): review it yourself before accepting - **do not accept purely
  because the score is high**. Two real examples from this pipeline's own history:
  - Score 96: `"not at all satisfied"` vs `"not so satisfied"` survey response categories - both
    score high on shared boilerplate text, but are different answers on a Likert scale.
  - Score 94-97: `שירותים ממלכתיים - חינוך` vs `שירותים ממלכתיים: חינוך` (dash vs colon) - looked
    like an obvious punctuation-only duplicate, but checking the actual column position revealed
    one came from the sheet's **income** section and the other from its **expense** section -
    genuinely different metrics that happened to collide on text after a hidden-header extraction
    bug flattened both to the same bare string (see Step 2). Fixing the extraction resolved this
    permanently; until you've fixed the extraction, don't trust a high score alone.

  If the meaning genuinely matches (confirmed via Step 6's checks, not just the score), confirm:
  ```
  lamas mapping confirm-fuzzy --orig "<orig_header text>"
  ```
  If it's actually a different concept, reject and let it stand alone (or point it elsewhere):
  ```
  lamas mapping reject-fuzzy --orig "<orig_header text>"                      # becomes its own canonical
  lamas mapping reject-fuzzy --orig "<orig_header text>" --canonical "<X>"    # or merge into a different existing one
  ```
- **`status == unresolved`** (no fuzzy candidate cleared the threshold): decide whether this
  raw header is a new variant of something that already exists in `header_mapping.yaml` (search
  it by keyword/substring - related concepts often share a distinctive word, but see Step 6 for why
  substring/fuzzy alone isn't always enough) or is a genuinely new metric. Present your reasoning
  and a recommendation to the user for confirmation before adding it, since this creates new
  taxonomy that persists going forward:
  ```
  lamas mapping add --canonical "<existing or new canonical text>" --orig "<orig_header text>"
  ```
  It's fine, and expected, to leave rare or genuinely ambiguous headers unresolved for a follow-up
  session (or an explicit user decision) rather than guessing - unresolved entries just stay in
  the pending report. A real example: a "total population at year end" header couldn't be safely
  merged into an existing canonical because that canonical's own historical data mixed units
  (some years already in absolute counts, others genuinely in thousands) - see Step 6's "check
  actual values, not just header text" for how this was caught, and flag findings like this to the
  user rather than silently picking a side.

## Step 4 - Keep config files in sync

Re-run to confirm convergence:
```
lamas map-headers --year <YEAR> --strict
```
This exits non-zero if any `unresolved` rows remain for the year. Loop back into Step 3 until it
passes, or stop deliberately and tell the user what's left unresolved and why (e.g. genuinely
ambiguous headers worth a second opinion, or a unit-consistency question you've flagged). Every
decision so far should already be reflected in `Lamas/data/sheet_config.yaml` and
`Lamas/data/header_mapping.yaml` - there is no other state to track or hand off.

## Step 5 - Finalize

```
lamas build
lamas qa
```
`build` (local output only by default) applies `specific_fixes`/`value_fixes` and writes the
final dataset to `Lamas/db_bkp/`. `qa` runs the full pytest quality-assurance suite
(`Lamas/tests/`), which encodes the checks a human used to do by eye in the old Airtable "Stats"
table (see Step 7 for the full list of checks) plus everything else in the test suite.

If both succeed, report a summary to the user: years covered, how many headers were newly mapped
or confirmed this session, which sheet_config entries were added/changed, and how many pending
headers (if any) remain unresolved. Then **suggest, but do not run yourself**, the production
Postgres push:
```
lamas build --output postgres
```
(or `--output local,postgres` to keep the local artifact too). This writes to the shared
`lamas_muni` table via `DATAFLOWS_DB_ENGINE` - it's a shared-system write, so it always needs the
user's explicit go-ahead, never automatic.

## Step 6 - How to actually review a pending header (do's and don'ts)

**Don't:**
- Accept a fuzzy suggestion because the score is high. Scores of 90-97 have been wrong in both
  directions found so far (false positives on genuinely different concepts that share
  boilerplate text; see Step 3's examples).
- Bulk-process a whole batch with one rule ("no candidate = self-map", "score > 90 = merge"). Both
  have produced real errors in this pipeline's history.
- Trust that a clean `diagnose` preview means the extraction is correct - see Step 2's hidden
  duplicate-header case.
- Merge two headers into an existing canonical without checking the canonical's own historical
  values when units or scale could plausibly differ (thousands vs absolute, area vs count, etc).

**Do:**
- Read the `orig_header`, `sample_values`, `years`, and `sheets` columns together - they usually
  tell you enough to judge intent (e.g. a percentage-shaped value range vs an absolute count).
- When a header name alone is ambiguous (e.g. it could plausibly be either an income or an expense
  line item), find its actual column position in the source sheet and look at neighboring headers
  / section markers (`סה"כ הכנסות בתקציב הרגיל` vs `סה"כ הוצאות בתקציב הרגיל` boundaries, or
  similar) to disambiguate - don't guess from the text in isolation:
  ```python
  from lamas.preprocess import locate_headers, clean
  from lamas.sheet_config import SheetConfig
  from openpyxl import load_workbook
  wb = load_workbook('Lamas/downloads/lamas-muni-<YEAR>.xlsx')
  sheet = wb['<sheet name>']
  data = [[clean(c.value) for c in row] for row in sheet.rows]
  layout = locate_headers(<YEAR>, '<sheet name>', data, SheetConfig.load().get(<YEAR>, '<sheet name>'))
  # layout.headers is the column-ordered list; find your header's index and print neighbors
  ```
- Before merging into a canonical that carries a unit qualifier (e.g. `(אלפים)`, `(אחוזים)`, a
  named unit like `(ש"ח)`/`(מ"ר)`), pull a couple of real values for that canonical across a few
  different years/municipalities from the checkpoint and sanity-check the scale is consistent
  before adding one more source into the mix.
- Remember `value_fixes()` (`Lamas/lamas/headers/value_fixes.py`) matches canonical header text
  **exactly** (e.g. `סה"כ אוכלוסייה (אלפים)`) to trigger its `x1000` conversions. If a canonical
  now carries a category prefix (e.g. `דמוגרפיה - סה"כ אוכלוסייה (אלפים)`), that exact-match check
  will **not** fire, silently skipping the intended conversion. If you confirm a canonical like
  this is meant to get a `value_fixes` conversion, either update `value_fixes()`'s match to account
  for the prefix, or flag it to the user - don't assume the conversion "just happens."
- When you find a real, pre-existing data-quality issue while reviewing (like the mixed-unit
  canonical above), report it clearly to the user rather than quietly working around it or
  picking a side yourself - these are exactly the judgment calls "human approval" exists for.

## Step 7 - The QA suite (`Lamas/tests/test_quality_report.py`)

Checks currently implemented:
- `test_mapping_yaml_valid` / `test_sheet_config_yaml_valid` - both YAML files parse and are
  internally consistent (no duplicate `orig` entries across canonicals).
- `test_no_near_duplicate_canonical_headers` - reports (doesn't hard-fail) canonical headers that
  are textually near-identical to each other, for human review.
- `test_all_mapping_entries_exist_in_source_data` - **hard gate**: every `orig` entry in
  `header_mapping.yaml` must actually appear in the real scraped data; catches stale/unused
  entries (e.g. left over after a `sheet_config.yaml` fix changes what text gets extracted - see
  Step 2's note on cleaning up orphaned entries).
- `test_canonical_headers_follow_naming_convention` - reports (doesn't yet hard-fail) canonical
  headers that don't follow the `{category} - {metric}` or `{category} - {metric} ({unit})` shape.
  **TODO**: tighten this into a hard gate once the historical backlog of non-conforming entries
  (ported mechanically, or self-mapped before this convention was settled) is cleaned up.
- `test_no_duplicate_headers_within_sheet` - **hard gate**: no header string may appear more times
  per `(year, sheet)` than there are distinct municipalities - the exact regression test for the
  hidden multi-row-header bug described in Step 2. If this fails for a year, it means two distinct
  columns are colliding under one header string; go fix `sheet_config.yaml`, don't map around it.
- `test_no_unresolved_headers_strict` - **hard gate**: zero `unresolved` rows in the current
  pending report; this is what "ingestion is done" actually means.
- `test_specific_fixes_invariants` / `test_row_counts_per_year_sheet_reported` /
  `test_sheet_config_has_no_gaps_for_downloaded_years` - as described in `CURRENT_BEHAVIOR.md`.

Run `lamas qa` (or `pytest Lamas/tests/`) as the final gate before suggesting the Postgres push.
