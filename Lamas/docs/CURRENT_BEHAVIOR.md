# Lamas pipeline — current behavior (pre-modernization baseline)

This document describes the `Lamas/` pipeline exactly as it operates as of this writing (2026-07-03, commit `4c25d06`), **before** any modernization changes. It exists so the modernization effort has a precise, reviewable baseline, and so institutional knowledge currently living only in notebook cells, Airtable, and hand-tuned code doesn't get lost in the rewrite.

## 1. Overview

The pipeline downloads Israel's Central Bureau of Statistics ("הלמ״ס" / CBS / "Lamas") yearly publication on local authorities ("הרשויות המקומיות") — a set of Excel workbooks, one per year from 1999 onward, each containing several sheets of municipal statistics (population, budget, area, education, environment, etc., depending on year). It reshapes these ugly, multi-row-header, wide-format spreadsheets into a tidy long-format table: one row per `(year, municipality, header, value)` tuple.

The output is intended to feed a shared Postgres database (`lamas_muni` table, in the `datacity` infrastructure) used by other analyses in this repo/organization, but as checked in today, the pipeline's only *active* write is a local CSV backup — the real DB write is present in code but commented out (see §8).

The entire pipeline is orchestrated by **one Jupyter notebook**, `Lamas/muni_processing.ipynb`, which has no markdown documentation cells — every explanation of *why* a step exists lives either in code comments, in this document, or in the heads of whoever last ran it.

## 2. Orchestration: `muni_processing.ipynb`, cell by cell

The notebook has 8 cells (cell 7 is empty/unused). None are markdown.

- **Cell 0**: `%reload_ext autoreload` / `%autoreload 2` — Jupyter convenience only, irrelevant outside the notebook.
- **Cell 1**: Imports `download_all`, `preprocess_files`, `process_headers`, `value_fixes`; loads `Lamas/.env` via `dotenv.load_dotenv('.env', override=True)`.
- **Cell 2**: `filenames = download_all()` — downloads every configured year's workbook (see §3), returns `{year: local_path}`. The human visually inspects the printed dict as a first sanity check (right years, right extensions).
- **Cell 3** — the expensive step: `data = process_headers(preprocess_files(filenames)).results()[0][0]`, then pickles the result to `Lamas/data.pickle`. The human watches per-year/per-sheet `PROCESSING ...` log lines and any `BAD FLOATS {...}` warnings (see §5) for anomalies.
- **Cell 4** (`if False:` — **disabled**): rebuilds a `header`/`orig_header`/`count` mapping from the freshly-pickled data, full-outer-joins it against the current Airtable `Header Mapping` table (keyed by `orig_header`, using `AIRTABLE_ID_FIELD` for correct upsert), and writes new/changed pairs back via `dump_to_airtable`. This is a maintenance/bootstrap flow for seeding or repairing the mapping table; it is switched off in the checked-in notebook.
- **Cell 5** (`if True:` — **active**): computes per-header statistics — `count`, `years` (array), `max_year`, `min_year` — via two chained `DF.join_with_self` aggregations, and upserts them into the Airtable **`Stats`** table (again keyed by `AIRTABLE_ID_FIELD`, full-outer-join). This is the pipeline's only current write to Airtable.
- **Cell 6** (`### WRITE TO DB`): reloads `data.pickle`, applies `value_fixes()` (§6), runs an inline `count()` generator that prints matching rows for a hardcoded spot-check (`row['name'] == 'רעננה' and 'עלות עבודה' in row['orig_header']`) plus periodic row-count progress prints, and writes the final dataset via `DF.dump_to_path('db_bkp')`. A `DF.dump_to_sql(dict(lamas_muni={...}), batch_size=1000)` call — the intended production write — is present but **commented out**, along with its `mode`/`indexes_fields` options.
- **Cell 7**: empty.

Verbatim reproduction of cells 4-6 is in the Appendix (§10) since they contain the only Airtable-write and DB-write logic in the whole codebase — nowhere else in `.py` files.

## 3. Stage 1 — Download (`Lamas/downloader.py`)

```python
BASE_URL = 'https://www.cbs.gov.il/he/publications/doclib/2019/hamakomiot1999_2017/'
DOWNLOADS_DIR = 'downloads'
MIN_YEAR = 1999
MAX_YEAR = 2022
XLSX_YEAR = 2016
P_LIBUD = {2022}
P_LIBUD2 = {2021}
```

`download_all()` creates `Lamas/downloads/` and calls `download_excel(year)` for every `year in range(MIN_YEAR, MAX_YEAR + 1)`, returning `{year: local_path}`.

`download_excel(year)`:
- Builds the "normal" filename `{year}.xls` (years `< 2016`) or `{year}.xlsx` (years `>= 2016`, per `XLSX_YEAR`).
- **Filename irregularity handling** (lines 16-21):
  ```python
  if year in P_LIBUD:
      filename = f'p_libud_{year % 1000}.xlsx'
  if year in P_LIBUD2:
      filename = f'p_libud_{year}.xlsx'
  else:
      filename = out_filename
  ```
  This is an `if / if / else` construct, **not** `if / elif / else`. For a year in `P_LIBUD` (currently just `2022`) but not in `P_LIBUD2`, line 17 sets `filename = 'p_libud_22.xlsx'`, but then the second `if` (line 18) is false for 2022, so its `else` (line 20-21) unconditionally runs and overwrites `filename` back to the normal pattern. **Net effect: the `P_LIBUD` branch is dead code as written — 2022 downloads under its ordinary `2022.xlsx` name regardless of this special-casing.** Only `P_LIBUD2` (2021) actually gets its special `p_libud_2021.xlsx` filename, because its `if` short-circuits the trailing `else`. This has apparently gone unnoticed because it happens to still produce a working download for 2022 (i.e., the ordinary CBS URL path also serves 2022 correctly today).
- Downloads via `requests.get(url, stream=True)`, `assert r.status_code == 200`, writes with `shutil.copyfileobj`. Skips if the local file already exists (no checksum/staleness check — a partially-written or wrong file must be deleted by hand to force a re-fetch).
- Output path: `Lamas/downloads/lamas-muni-{year}.{ext}`.

**Known gap**: `Lamas/downloads/` already contains `lamas-muni-2023.xlsx` and `lamas-muni-2024.xlsx` (dated 2026-07-03, i.e. fetched very recently by some means outside this code), but `MAX_YEAR=2022` means `download_all()` cannot reach 2023/2024 as written — they were added by an out-of-band manual process. As of this writing, `downloads/` holds 26 files, years 1999-2024, `.xls` through 2015, `.xlsx` from 2016.

## 4. Stage 2 — Per-year/per-sheet config (`Lamas/config.py`)

```python
@dataclass
class Config:
    header_rows: int = 1
    extend_headers_top: int = 0
    extend_headers_bottom: int = 0
    skip: bool = False
```

`CONFIGURATION: dict[int, dict[str, Config]]` overrides the defaults only where the CBS workbook layout requires it. Full contents as of this writing:

| Year | Sheet (Hebrew) | Override | Why (inferred from context) |
|---|---|---|---|
| 2000 | `עיריות ומועצות מקומיות` | `skip=True` | Sheet layout not supported / not needed |
| 2001 | `עיריות ומועצות מקומיות` | `skip=True` | Same |
| 2016 | `נתונים פיזיים ונתוני אוכלוסייה` | `header_rows=4, extend_headers_top=2` | CBS introduced a taller, multi-row header block starting this year |
| 2016 | `נתוני תקציב` | `header_rows=4, extend_headers_top=2` | Same |
| 2017 | `נתונים פיזיים ונתוני אוכלוסייה` | `header_rows=4, extend_headers_top=2` | Layout carried over |
| 2017 | `נתוני תקציב` | `header_rows=5, extend_headers_top=2` | Budget sheet grew one more header row |
| 2018 | `נתונים פיזיים ונתוני אוכלוסייה` | `header_rows=4, extend_headers_top=2` | |
| 2018 | `נתוני תקציב` | `header_rows=5` (no top-extend) | |
| 2019 | `נתונים פיזיים ונתוני אוכלוסייה` | `header_rows=4, extend_headers_top=2` | |
| 2019 | `נתוני תקציב` | `header_rows=5, extend_headers_top=1` | |
| 2020 | `נתונים פיזיים ונתוני אוכלוסייה` | `header_rows=4, extend_headers_top=2` | |
| 2020 | `נתוני תקציב` | `header_rows=5, extend_headers_top=1` | |
| 2021 | `נתונים פיזיים ונתוני אוכלוסייה` | `header_rows=4, extend_headers_top=2` | |
| 2021 | `נתוני תקציב` | `header_rows=2, extend_headers_top=1` | Budget sheet layout shrank back down |
| 2021 | `נתוני הסקר החברתי` | `skip=True` | Social survey sheet — different shape, deliberately excluded |
| 2021 | `סקרי כוח אדם והוצאות משק בית` | `skip=True` | Labor force / household expenditure survey — same reason |
| 2022 | (all four entries identical to 2021) | | |

No entries exist for 1999, 2002-2015 — these years work fine under the all-defaults `Config()`. **No entries exist for 2023/2024** — those workbooks, already downloaded, cannot be correctly parsed today without someone adding config for them (their layout is unverified as of this writing).

## 5. Stage 3 — Sheet parsing (`Lamas/preprocess.py`)

### Entry points
- `preprocess_files(filenames)` → for each `(year, filename)`, calls `preprocess_file`.
- `preprocess_file(year, filename)` → dispatches on extension: `.xlsx` via `openpyxl.load_workbook`, else `xlrd.open_workbook`. For each sheet, skips if `sheet.max_column/nrows < MIN_SIZE=30` or `max_row/ncols < MIN_SIZE=30` (tiny sheets are assumed irrelevant/metadata). Materializes the whole sheet into a 2D Python list via `clean()` (whitespace-normalizes strings), then calls `process_sheet(year, sheet_name, data, filename)`.

### `process_sheet` — the core heuristic

1. Look up `Config` for `(year, sheet_name)` from `CONFIGURATION`, defaulting to `Config()`. Return immediately if `skip`.
2. **Anchor detection**: scan the first `HEADER_SIZE=5` rows and first 5 columns of every row for string cells matching any of the `MAGICS` regexes:
   ```python
   MAGICS = [
       'סמל הרשות',            # authority code
       '^מחוז',                # district (start-of-string anchor)
       'מעמד מוניציפאלי',       # municipal status
       'מיסים ומענקים',         # taxes and grants
       'שם הרשות',              # authority name
       'גירעון מצטבר בסוף שנה', # accumulated deficit at year end
       'סמל רשות מקומית',       # local authority code (alt phrasing)
   ]
   ```
   For each magic, record the first matching cell's `(row, col)` position → `magic_pos`. `assert len(magic_pos) >= 2` — a sheet needs at least 2 anchors found or the whole run aborts with an `AssertionError`.
3. **Orientation detection**: if the first two anchors share a column (`magic_pos[0][1] == magic_pos[1][1]`), the sheet is transposed (headers run down rows, data across columns) and `get(r,c)` is remapped accordingly; if they share a row, it's the normal orientation; otherwise `assert False` aborts.
4. **Multi-row header reconstruction**: walks columns (`c = 0, 1, 2, ...`) building a `headers_front` buffer of size `config.header_rows`, filling in non-empty, non-"שנת עדכון" (update year) fragments, clearing lower buffer slots once a Hebrew-lettered fragment is set (so a filled label doesn't get overwritten by a stale value below it), joins non-empty fragments with `/` into one header string per column. Detects the municipality-name column (`שם הרשות`/`סמל הרשות` fragment) and resets the header buffer there; `assert name_idx is not None` if never found. Purely-numeric headers are dropped from the carry-forward buffer (`len(LETTERS.findall(v))==0` check) so stray numbers (e.g. a year printed above a column) don't leak into unrelated headers downstream.
5. **Row extent detection**: scans downward from the header block until a fully-empty row is hit, tracking `max_r` as the last row where more than `MIN_SIZE/2=15` cells were populated (a soft "this row is mostly real data" heuristic).
6. **Row emission**: for each row up to `max_r`, for each `(header, value)` pair except the name column itself, cleans the value via `fix_value()` and yields `dict(year=year, name=muni_name, header=h, value=v, filename=filename)`. **Note**: the dict literally has a commented-out `# sheet=name,` line (source line 193) — the sheet name is deliberately available here but discarded before today's output.

### `fix_value(v, bad_floats)`
- Returns `None` for sentinel/empty values: `-`, `..`, empty string, `.`, or `None`.
- Returns `None` for any value containing `http` (a stray URL in a data cell).
- Returns the value unchanged if it contains any Hebrew letters (non-numeric, don't touch).
- Otherwise: strips `,` and `*`, strips whitespace, unwraps a value fully wrapped in parens (`(123)` → `123` — a common accounting convention for negative numbers, note: the sign is **not** applied, just the parens removed), strips a trailing `.0`.
- Attempts `float(v)` purely to detect values that still don't parse as numbers; any failures are added to a `bad_floats` set (not raised, not fixed) which is printed as `BAD FLOATS {...}` once at the end of `process_sheet` if non-empty — a real example seen during 2017 processing was a stray unevaluated spreadsheet formula string, `=Q94/R94100`.

### Failure modes
- **`assert`-based control flow throughout** (magic-position count, orientation validity, name-index found, "bad header" detection) means any single sheet's layout surprise raises an unhandled `AssertionError` that **aborts the entire multi-year run** — there is no per-sheet isolation or recovery today.
- All diagnostics are `print()`-based (`PROCESSING ...`, `BAD FLOATS ...`, `ERROR ...` on a name-extraction crash) — nothing is captured/logged for later inspection beyond notebook output scrollback.

## 6. Stage 4 — Header normalization & translation (`Lamas/process_headers.py`)

### `fix_years()`
A `dataflows` step. For each row: strips comparison-year phrases (`לעומת 2019` → `לעומת`, via `COMPARE_YEAR = re.compile('לעומת [0-9]{4}')`), captures Hebrew-calendar year tokens (`HEBYEAR = re.compile('תש["״][א-ת]|תש[א-ת]["״][א-ת]')`) into a `hebyears` set (diagnostic only — printed once at the end via a `DF.finalizer`, never stored), then strips them from the header text. Extracts embedded calendar years via three regexes applied in sequence — `YEAR_RANGE` (`2016-2017` style), `YEAR_EXT` (`2016/17` style), `YEAR` (bare 4-digit) — removing each match from the header text as it's found. `1990` is explicitly discarded from the candidate-years set if found (`if '1990' in years: years.remove('1990')` — an unexplained special case, likely a known false-positive). Sets `row['year']` to the max embedded year found (capped at the row's original year — never allowed to exceed it) and `row['min_year']` to the min. Rewrites `row['header']` with all matched year tokens removed and whitespace/slashes cleaned up (`MULTI_WS`, stripped leading/trailing `/- `, collapsed `//` and ` /`).

### Airtable dependency — `process_headers(data)`, lines 197-204
```python
translations = DF.Flow(
    load_from_airtable('apptGe94qTaLjk5Fr', 'Header Mapping', 'Grid view', 'env://AIRTABLE_API_KEY'),
).results()[0][0]
translations = dict(
    (x['orig_header'].strip(), x['header'].strip()) for x in translations
)
```
This is the **only hard runtime dependency on Airtable in the entire codebase**. Base `apptGe94qTaLjk5Fr`, table `Header Mapping`, view `Grid view`, credential from `env://AIRTABLE_API_KEY` (i.e. `AIRTABLE_API_KEY` from `.env`). There is **no error handling** — if Airtable is unreachable, the API key is invalid/expired, or the table is empty/misshapen, this throws an unhandled exception and the pipeline cannot proceed at all.

### `translate_headers(headers, translations)`
Given the full list of raw headers (most-common-first via `Counter`) and the Airtable-sourced `translations` dict:
- **O(n²) self-fuzzy-matching**: for every pair of headers not yet in `headers_map`, digit-collapses both (`DIGITS = re.compile('([0-9-]{2,})')`, replacing runs of 2+ digits/hyphens with a fixed 5-copy repeat so headers differing only in embedded numbers still compare as similar) and computes `thefuzz.fuzz.ratio(ii, jj)`. If `> 95`, maps the later header to the earlier ("more common") one in `headers_map`. This clusters near-duplicate headers that were *not already resolved by the Airtable mapping* — entirely separate from and in addition to the human-curated mapping.
- For each row: sets `row['orig_header'] = h` (the raw, pre-translation header) **before** any translation is applied; if `h` is in the Airtable `translations` dict, uses that; otherwise falls back to the fuzzy `headers_map`, or leaves `header` unchanged if neither resolves. The first time a header is seen with no Airtable translation, it's printed as `FOUND MISSING TRANSLATION {h}` (a `missing` set dedupes repeat prints) — **this is the only diagnostic of "we don't know how to map this header" and it is never persisted anywhere**, just scrolled past in notebook output.

### `specific_fixes()`
Row-generator with three hardcoded, unconditional patches:
1. Drop all rows where `name == 'נוף הגליל'` (Nof HaGalil) and `year < 2001` — this city was formed by a later merger/rename (of what was previously "Nazareth Illit"), so any pre-2001 data recorded under this exact name is considered spurious.
2. Rename `name == 'תל אביב -יפו'` (stray space before the hyphen) → `'תל אביב-יפו'`.
3. Rename `name == 'הרצלייה'` (double-yod spelling) → `'הרצליה'`.

### `value_fixes()`
Applied only in notebook cell 6, right before final output — not part of `process_headers()`. For each row with a non-empty, `Decimal`-parseable value:
- `header == 'סה"כ אוכלוסייה (אלפים)'` (total population, in thousands) → `value *= 1000`, header renamed to `'סה"כ אוכלוסייה'` (thousands suffix dropped).
- Same pattern for `'סה"כ גברים (אלפים)'` (men) and `'סה"כ נשים (אלפים)'` (women).
- Any header ending in `'(שטח במ"ר)'` (area in m²) → `value /= 1000`, header renamed to the same string with `'(שטח באלפי מ"ר)'` (thousands of m²) substituted in.
- Two open `#TODO` comments, never implemented: merging `'גמר של סלילת כבישים חדשים'` and `'גמר של הרחבה ושיקום של כבישים חדשים'` (new-road-paving-completion categories) into a single combined header, and the equivalent for their `'התחלה...'` (start-of-construction) counterparts.
- Any exception during the `Decimal(value)` conversion is silently swallowed (`except: pass`) — the row passes through with its original string value untouched.

## 7. The Airtable `Stats` table — today's only QA mechanism

Notebook cell 5 computes, per distinct `header` value across the whole dataset: `count` (total row occurrences), `years` (the full array of years it appeared in), `min_year`, `max_year`. This is upserted into Airtable base `apptGe94qTaLjk5Fr`, table `Stats`, keyed by `header` via a full-outer-join against the table's existing rows (matched by `AIRTABLE_ID_FIELD`).

**This table, viewed by a human in the Airtable UI after each run, is the entire current quality-assurance process.** Based on the fields available and the presence of the fuzzy-merge logic in `translate_headers()`, the review a human is expected to perform is:
- **Suspiciously low `count`** relative to a header's expected frequency (24+ years × ~200 municipalities) suggests either a genuine rare metric, or — more often — a header that should have been merged with a near-identical one that has most of the volume (a fuzzy-match miss, or a header whose wording changed across years in a way the `>95` threshold didn't catch).
- **Narrow or non-contiguous `years` ranges** (e.g. a header appearing in only 2-3 years out of 24) flags either a metric CBS genuinely only published briefly, or — again — a header whose exact text drifted just enough between years to break the mapping/fuzzy-match.
- **Apparent near-duplicates** sitting as separate rows in the `Stats` grid (visually similar Hebrew text, easy to spot by eye scanning a sorted table) prompt the human to go edit the `Header Mapping` table directly, adding the "wrong" `orig_header` variant under the "right" canonical `header`.

None of this triage logic is automated or written down anywhere else — it depends entirely on a human's judgment while scanning an Airtable grid view, and is not reproducible or auditable from the codebase alone.

## 8. Output artifacts

| Artifact | Producer | Size (as of writing) | Schema | Status |
|---|---|---|---|---|
| `Lamas/data.pickle` | Notebook cell 3, `pickle.dump(process_headers(preprocess_files(filenames)).results()[0][0])` | 183 MB | `year:int, name:str, header:str, value:str\|None, filename:str, min_year:int, orig_header:str` | Intermediate — post header-normalization, **pre** `value_fixes()` |
| `Lamas/db_bkp/res_1.csv` (+ `datapackage.json`) | Notebook cell 6, `DF.dump_to_path('db_bkp')` after `value_fixes()` | 450 MB, 2,027,002 data rows | same fields as above, values post-conversion | **The only currently-active final write** |
| Postgres `lamas_muni` table | `DF.dump_to_sql(...)` in cell 6 | — | — | **Commented out / dormant.** Reached via `.env`'s `DATAFLOWS_DB_ENGINE` connection string, itself reached via `kubectl port-forward -n datacity importer-db-<pod> 55432:5432` (per a comment directly above that env var) — i.e. the real destination is a Kubernetes-hosted Postgres instance in the `datacity` namespace, accessed through a manual port-forward, not a direct connection string. This is the intended production consumer but is not being written to today. |
| Airtable `Header Mapping` table | Read every run; written only by disabled cell 4 | 2056+ rows (per `header_mappings/` snapshot, see below) | `header`, `orig_header`, plus Airtable record id | Read: active. Write: disabled. |
| Airtable `Stats` table | Cell 5 | — | `header`, `count`, `years`, `min_year`, `max_year`, plus Airtable record id | Active (read+write every run) |

`Lamas/header_mappings/` (added once in commit `122f90b`, never referenced by any code since) contains a stale local export of what the Airtable `Header Mapping` table looked like at some point: `res_1.csv` (`header,orig_header,count`, 2056 rows — confirmed to contain genuine muni-budget terms like `גירעון מצטבר` mixed with header text from apparently *unrelated* CBS reports, e.g. topography/elevation and water-consumption statistics, suggesting the Airtable base may have been shared across more than this one dataset at some point) and `data/headers.csv` (`orig_header,header,count`, 1200 rows, cleaner/more muni-specific — structurally matching the local staging file `dataflows_airtable`'s `dump_to_airtable` writes before pushing to Airtable, per the `DF.update_resource(-1, name='headers', path='data/headers.csv')` calls in notebook cells 4-5).

## 9. Known issues catalogue

| # | Issue | Location | Impact |
|---|---|---|---|
| 1 | `P_LIBUD`/`P_LIBUD2` use `if/if/else` instead of `if/elif/else` | `downloader.py:16-21` | `P_LIBUD` (2022) special-case filename is silently dead code |
| 2 | `MAX_YEAR=2022` is stale | `downloader.py:8` | 2023/2024 workbooks exist locally but weren't fetched by this code, and can't be re-fetched/verified by it either |
| 3 | No `CONFIGURATION` entries for 2023/2024 | `config.py` | Those workbooks cannot be parsed by `preprocess.py` today |
| 4 | Bare, non-relative import | `preprocess.py:6` (`from config import ...`) | Only works with `Lamas/` on `PYTHONPATH`/cwd — blocks proper packaging; `.env`'s `PYTHONPATH` var exists solely to work around this |
| 5 | Hard, unhandled Airtable dependency | `process_headers.py:197-204` | Pipeline cannot run at all if Airtable is unreachable, key is invalid, or the table is empty; zero error handling |
| 6 | Self-referential O(n²) fuzzy merge, not persisted | `process_headers.py:75-114` | Non-deterministic-feeling clustering (depends on `Counter.most_common()` tie ordering) that silently rewrites headers with no audit trail; "missing translation" diagnostic is print-only |
| 7 | `assert`-based control flow throughout | `preprocess.py` (multiple) | Any single sheet's layout surprise aborts the *entire* multi-year run; no per-sheet isolation |
| 8 | `print()` used for all diagnostics | `preprocess.py`, `process_headers.py` | Nothing captured/logged beyond notebook scrollback |
| 9 | Dead import | `process_headers.py:2` (`from struct import pack`) | Unused |
| 10 | `hebyears` diagnostic collected but never persisted | `process_headers.py:21,71` | Printed once at end of `fix_years()`, then discarded |
| 11 | Two unimplemented `#TODO`s | `process_headers.py:178-179` | Road-paving-completion headers never get merged as intended |
| 12 | `sheet` name discarded during row extraction | `preprocess.py:193` (commented out) | No way to trace a row back to its source sheet without re-deriving it |
| 13 | No dependency manifest anywhere in the repo | (repo-wide) | Implicit deps: `dataflows==0.5.9`, `dataflows-airtable==0.2.5`, `thefuzz==0.20.0`, `openpyxl==3.1.5`, `xlrd==2.0.1`, plus `requests`, `python-dotenv` |
| 14 | Large, untracked working-tree artifacts | `Lamas/data.pickle` (183MB), `Lamas/db_bkp/` (450MB) | No defined intermediate-storage strategy; sit in the working tree, `git status` shows them as untracked (`??`) rather than gitignored |
| 15 | Stale, code-unreferenced backup directories | `Lamas/downloads.bkp/`, `Lamas/downloads.bkp2/` | Historical manual snapshots, safe to remove |
| 16 | `Lamas/header_mappings/` unreferenced by any code | `Lamas/header_mappings/` | One-time Airtable export snapshot from commit `122f90b`, never touched since |
| 17 | The Postgres write path is dormant | notebook cell 6 (commented out) | The pipeline's intended production output is not actually being produced today |

## 10. Appendix

### 10.1 `CONFIGURATION` dict (verbatim, `config.py`)

```python
CONFIGURATION = {
    2000: {
        'עיריות ומועצות מקומיות': Config(skip=True),
    },
    2001: {
        'עיריות ומועצות מקומיות': Config(skip=True),
    },
    2016: {
        'נתונים פיזיים ונתוני אוכלוסייה': Config(header_rows=4, extend_headers_top=2),
        'נתוני תקציב': Config(header_rows=4, extend_headers_top=2),
    },
    2017: {
        'נתונים פיזיים ונתוני אוכלוסייה': Config(header_rows=4, extend_headers_top=2),
        'נתוני תקציב': Config(header_rows=5, extend_headers_top=2),
    },
    2018: {
        'נתונים פיזיים ונתוני אוכלוסייה': Config(header_rows=4, extend_headers_top=2),
        'נתוני תקציב': Config(header_rows=5),
    },
    2019: {
        'נתונים פיזיים ונתוני אוכלוסייה': Config(header_rows=4, extend_headers_top=2),
        'נתוני תקציב': Config(header_rows=5, extend_headers_top=1),
    },
    2020: {
        'נתונים פיזיים ונתוני אוכלוסייה': Config(header_rows=4, extend_headers_top=2),
        'נתוני תקציב': Config(header_rows=5, extend_headers_top=1),
    },
    2021: {
        'נתונים פיזיים ונתוני אוכלוסייה': Config(header_rows=4, extend_headers_top=2),
        'נתוני תקציב': Config(header_rows=2, extend_headers_top=1),
        'נתוני הסקר החברתי': Config(skip=True),
        'סקרי כוח אדם והוצאות משק בית': Config(skip=True),
    },
    2022: {
        'נתונים פיזיים ונתוני אוכלוסייה': Config(header_rows=4, extend_headers_top=2),
        'נתוני תקציב': Config(header_rows=2, extend_headers_top=1),
        'נתוני הסקר החברתי': Config(skip=True),
        'סקרי כוח אדם והוצאות משק בית': Config(skip=True),
    },
}
```

### 10.2 `MAGICS` anchor list (verbatim, `preprocess.py:8-16`)

```python
MAGICS = [
    'סמל הרשות',              # authority code
    '^מחוז',                  # district
    'מעמד מוניציפאלי',         # municipal status
    'מיסים ומענקים',           # taxes and grants
    'שם הרשות',                # authority name
    'גירעון מצטבר בסוף שנה',   # accumulated deficit at year end
    'סמל רשות מקומית',         # local authority code (alt phrasing)
]
```

### 10.3 `specific_fixes()` and `value_fixes()` (verbatim, `process_headers.py:133-182`)

```python
def specific_fixes():
    def func(rows):
        for row in rows:
            name = row['name']
            header = row['header']
            value = row['value']
            year = row['year']
            if name == 'נוף הגליל' and year < 2001:
                continue
            if name == 'תל אביב -יפו':
                row['name'] = 'תל אביב-יפו'
            if name == 'הרצלייה':
                row['name'] = 'הרצליה'
            yield row
    return func


def value_fixes():
    def func(rows):
        for row in rows:
            name = row['name']
            header = row['header']
            value = row['value']
            year = row['year']
            if value:
                try:
                    value = Decimal(value)
                    if header == 'סה"כ אוכלוסייה (אלפים)':
                        value *= 1000
                        row['header'] = 'סה"כ אוכלוסייה'
                        row['value'] = str(value)
                    if header == 'סה"כ גברים (אלפים)':
                        value *= 1000
                        row['header'] = 'סה"כ גברים'
                        row['value'] = str(value)
                    if header == 'סה"כ נשים (אלפים)':
                        value *= 1000
                        row['header'] = 'סה"כ נשים'
                        row['value'] = str(value)
                    if header.endswith('(שטח במ"ר)'):
                        value /= 1000
                        row['header'] = header.replace('(שטח במ"ר)', '(שטח באלפי מ"ר)')
                        row['value'] = str(value)
                except:
                    pass
                #TODO join 'גמר של סלילת כבישים חדשים' and 'גמר של הרחבה ושיקום של כבישים חדשים' to 'גמר של סלילת כבישים חדשים, הרחבה ושיקום של כבישים'
                #TODO same for 'התחלה...'

            yield row
    return func
```

### 10.4 Notebook cells 4-6 (verbatim, the only Airtable-write / DB-write logic in the codebase)

```python
# Cell 4 (disabled, if False:)
if False:
    import dataflows as DF
    from collections import Counter
    from dataflows_airtable import load_from_airtable, dump_to_airtable, AIRTABLE_ID_FIELD
    import pickle

    with open('data.pickle', 'rb') as f:
        data = pickle.load(f)

    print('GETTING MAPPING', len(data))
    mapping = DF.Flow(
        data,
        DF.select_fields(['header', 'orig_header']),
        DF.update_resource(-1, name='headers'),
        DF.join_with_self('headers', ['orig_header', 'header'], dict(header=None, orig_header=None)),
    ).results()[0][0]
    print('GOT MAPPING', len(mapping))

    DF.Flow(
        load_from_airtable('apptGe94qTaLjk5Fr', 'Header Mapping', 'Grid view', 'env://AIRTABLE_API_KEY'),
        DF.select_fields([AIRTABLE_ID_FIELD, 'header', 'orig_header']),
        DF.update_resource(-1, name='current'),
        mapping,
        DF.update_resource(-1, name='headers', path='data/headers.csv'),
        DF.add_field('count', 'integer', 1),
        DF.join('current', ['orig_header'], 'headers', ['orig_header'], {AIRTABLE_ID_FIELD:None}, mode='full-outer'),
        DF.set_type('count', transform=lambda v: 1 if v else 0),
        dump_to_airtable({
            ('apptGe94qTaLjk5Fr', 'Header Mapping'): {
                'resource-name': 'headers',
            }
        }, 'env://AIRTABLE_API_KEY'),
    ).process()


# Cell 5 (active, if True:)
if True:
    import dataflows as DF
    from collections import Counter
    from dataflows_airtable import load_from_airtable, dump_to_airtable, AIRTABLE_ID_FIELD

    with open('data.pickle', 'rb') as f:
        data = pickle.load(f)

    mapping = DF.Flow(
        data,
        DF.select_fields(['header', 'year']),
        DF.update_resource(-1, name='headers'),
        DF.join_with_self('headers', ['header', 'year'], dict(
            header=None,
            year=None,
        )),
        DF.sort_rows('{year}'),
        DF.join_with_self('headers', ['header'], dict(
            header=None,
            years=dict(name='year', aggregate='array'),
            count=dict(aggregate='count'),
            max_year=dict(name='year', aggregate='max'),
            min_year=dict(name='year', aggregate='min')
        )),
    ).results()[0][0]
    print(mapping[:10])

    DF.Flow(
        load_from_airtable('apptGe94qTaLjk5Fr', 'Stats', 'Grid view', 'env://AIRTABLE_API_KEY'),
        DF.select_fields([AIRTABLE_ID_FIELD, 'header']),
        DF.update_resource(-1, name='current'),
        mapping,
        DF.update_resource(-1, name='headers', path='data/headers.csv'),
        DF.join('current', ['header'], 'headers', ['header'], {AIRTABLE_ID_FIELD:None}, mode='full-outer'),
        DF.set_type('count', transform=lambda v: v or 0),
        DF.set_type('years', type='string', transform=lambda v: ','.join(sorted(map(str,v))) if v else ''),
        dump_to_airtable({
            ('apptGe94qTaLjk5Fr', 'Stats'): {
                'resource-name': 'headers',
            }
        }, 'env://AIRTABLE_API_KEY'),
    ).process()


# Cell 6 (### WRITE TO DB)
import dataflows as DF

with open('data.pickle', 'rb') as f:
    data = pickle.load(f)

def count(rows):
    for i, row in enumerate(rows):
        if row['name'] == 'רעננה' and 'עלות עבודה' in row['orig_header']:
            print(row)
        yield row
        if i in (1, 10, 100, 1000, 2000, 5000) or i % 100000 == 0:
            print(i)


dp, _ = DF.Flow(
    data,
    value_fixes(),
    DF.update_resource(-1, name='lamas'),
    count,
    # DF.dump_to_sql(dict(
    #     lamas_muni={
    #         'resource-name': 'lamas',
    #         # 'mode': 'rewrite',
    #         # 'indexes_fields': [
    #         #     ['name', 'year', 'header'],
    #         # ],
    #     }
    # ), batch_size=1000),
    DF.dump_to_path('db_bkp')
).process()
dp.descriptor
```
