# Lamas

Downloads, parses, and normalizes the Israeli Central Bureau of Statistics ("Lamas") yearly
municipal statistics workbooks (1999-2024, one Excel file per year) into tidy
`(year, name, header, value, filename)` rows, ready to load locally or into Postgres.

There is no Jupyter notebook and no Airtable dependency - everything runs through the `lamas` CLI,
backed by two local YAML config files that are the only state that needs to persist between runs:

- `data/sheet_config.yaml` - per-year/per-sheet Excel layout overrides (header row counts, which
  sheets to skip, etc.)
- `data/header_mapping.yaml` - canonical header name -> list of raw header text variants seen
  across 26 years of shifting CBS spreadsheet layouts

If you're looking for the deep history of *why* the pipeline works the way it does (the original
pre-modernization behavior, bugs found along the way, etc.), see `docs/CURRENT_BEHAVIOR.md`.

## Setup

```bash
pip install -e ".[dev]"   # from inside Lamas/; [dev] adds pytest + the one-time Airtable seed script
```

This registers the `lamas` console script. A `.env` file (not committed) holds
`DATAFLOWS_DB_ENGINE` (a Postgres connection string) if you intend to push output there, and
`AIRTABLE_API_KEY`, only needed for `scripts/seed_mapping_from_airtable.py` (a one-time migration
helper, not part of normal operation).

## The `lamas` CLI

Every step of the pipeline is its own subcommand, so you can run the whole thing (`full-run`) or
drop into just the step you need while iterating on a new year.

| Command | What it does |
|---|---|
| `lamas download [--year Y]` | Download one year, or every year configured in `downloader.py` (idempotent - skips files already on disk). |
| `lamas diagnose --year Y [--sheet NAME]` | Dry-run parse of a workbook against the *current* `sheet_config.yaml`, without writing anything. Prints, per sheet: row/column counts, detected name-column index, a preview of the first extracted headers, or the exact parse error. This is the tool for iteratively tuning `sheet_config.yaml` for a new or misbehaving year. |
| `lamas config show --year Y` | Print the effective sheet config (defaults + overrides) for that year. |
| `lamas config set-sheet --year Y --sheet NAME [--header-rows N] [--extend-top N] [--extend-bottom N] [--skip/--no-skip]` | Create/update one sheet's config entry; rewrites `sheet_config.yaml` deterministically. |
| `lamas preprocess [--year Y] [--checkpoint PATH]` | Parse the downloaded workbook(s) and write a parquet checkpoint (default `.cache/preprocessed.parquet`) - this is the expensive step (~2-3 min for the full 1999-2024 corpus). |
| `lamas map-headers [--year Y] [--strict]` | Resolve every row's raw header against `header_mapping.yaml` and (re)write `reports/pending_headers.csv` for anything that didn't resolve cleanly. `--strict` exits non-zero if any row is fully `unresolved` (useful in CI). |
| `lamas mapping add --canonical "..." --orig "..."` | Add a raw header as a variant of a canonical (existing or brand new). |
| `lamas mapping confirm-fuzzy --orig "..."` | Accept the fuzzy-match suggestion already recorded for a pending row in `pending_headers.csv`. |
| `lamas mapping reject-fuzzy --orig "..." [--canonical "..."]` | Override a fuzzy suggestion: map to a different canonical, or omit `--canonical` to make it a brand-new one. |
| `lamas stats [--year Y]` | Regenerate `reports/header_stats.{csv,md}` - per-header row counts and year coverage, the local replacement for eyeballing the old Airtable "Stats" table. |
| `lamas build [--strict] [--output local,postgres] [--output-dir PATH]` | Apply `specific_fixes`/`value_fixes` and write the final output. `--strict` refuses to build while any header is unresolved. Defaults to local-only output; `postgres` pushes the resulting CSV via `push-postgres` below. |
| `lamas push-postgres [--csv PATH] [--table lamas_muni] [--truncate/--no-truncate]` | Push an already-built CSV (default `db_bkp/res_1.csv`) into Postgres via `psql \copy`. Reads the connection string from the `DATAFLOWS_DB_ENGINE` env var. Truncates the table first by default (matching a full-replace, not an incremental append) - a destructive, shared-system write, never run automatically. |
| `lamas full-run [--year Y] [--strict] [--output ...]` | `download` -> `preprocess` -> `map-headers` -> `stats` -> `build`, one shot. |
| `lamas qa` | Runs the full pytest suite under `tests/` - the automated quality gate (see below). |

Run `lamas <command> --help` for the full flag list on anything above.

### Pushing to Postgres

`DATAFLOWS_DB_ENGINE` is not auto-loaded from `.env` (nothing in the package calls
`load_dotenv()`) - export it into your shell first:
```bash
set -a; source Lamas/.env; set +a
```
Then either let `build` push it as part of the pipeline (`lamas build --strict --output local,postgres`),
or push a CSV you already have on hand directly:
```bash
lamas push-postgres --csv db_bkp/res_1.csv
```
A manually-triggered GitHub Action (`.github/workflows/push-postgres.yml`) runs this same flow
using a repo secret - see that workflow file for details. It is never triggered automatically.

### Quality assurance

`lamas qa` (or plain `pytest tests/`) runs the same checks a human used to do by eye in Airtable's
"Stats" table, now automated: no unresolved headers, no near-duplicate or unit-mixed canonicals in
`header_mapping.yaml`, no duplicate header collisions within a sheet, sane per-year/sheet row
counts, and year-over-year header coverage (a header reported in 5 straight years must still be
reported in the 6th, catching silently broken extractions - see `tests/test_quality_report.py` for
the full list and the reasoning behind each check, including the small set of already-investigated
exceptions that are allowed to stay).

CI (`.github/workflows/lamas-tests.yml`) runs this same suite on every PR touching `Lamas/`,
downloading and preprocessing the real data first (cached between runs) so the data-dependent
checks actually execute rather than skip.

## The `lamas-ingest` skill

`.claude/skills/lamas-ingest/SKILL.md` is a Claude Code skill that walks through ingesting one
year end-to-end, orchestrating the CLI above rather than reimplementing any parsing logic. Invoke
it (or just ask Claude to "ingest year X") when a newly-published CBS workbook needs onboarding, or
when an existing year has unresolved headers or config gaps.

It encodes one hard rule worth knowing even if you're doing this by hand: **every unmapped header
gets resolved one by one, by a tight heuristic or explicit semantic review - never in bulk, and
never just because "no better candidate was found."** An earlier version of this process got this
wrong once (bulk-accepting ~800 headers with no cross-checking), which fragmented what should have
been single metrics into near-duplicate canonicals. The skill file explains what a real per-header
review looks like, with worked examples of fuzzy-match suggestions that looked right but weren't.

## Walkthrough: ingesting a new year's Excel file

This is what the skill above automates, spelled out as a manual sequence of CLI calls:

1. **Download it.**
   ```bash
   lamas download --year 2025
   ```
   Confirms the file lands in `downloads/`. If CBS has changed their URL/filename pattern (rare,
   but check `lamas/downloader.py`'s `P_LIBUD`/`P_LIBUD2` special cases if this fails), fix the
   pattern there first.

2. **Get it parsing correctly.**
   ```bash
   lamas diagnose --year 2025
   ```
   Look at the header preview for every sheet. A new year usually parses fine using the previous
   year's layout, but watch for: sheets with suspiciously few headers, obviously truncated/mis-joined
   header text, or an outright parse error. For any sheet that looks wrong, adjust its config and
   re-check:
   ```bash
   lamas config set-sheet --year 2025 --sheet "נתוני תקציב" --header-rows 4 --extend-top 2
   lamas diagnose --year 2025 --sheet "נתוני תקציב"
   ```
   Repeat until every sheet's header preview looks like real column labels, or mark a sheet
   `--skip` if it's legitimately irrelevant (matches the historical pattern of skipped
   social-survey/labor-force sheets).

3. **Build a checkpoint and find unmapped headers.**
   ```bash
   lamas preprocess
   lamas map-headers --year 2025
   ```
   Check the summary line (`N unresolved, M auto-resolved needing confirmation`) and open
   `reports/pending_headers.csv`.

4. **Resolve every pending header - one at a time.**
   - For each `auto_resolved_needs_confirmation` row: look at the `suggested_canonical` and
     `suggested_score`, compare against the raw header text and a few `sample_values`, and either:
     ```bash
     lamas mapping confirm-fuzzy --orig "<orig_header>"          # suggestion is correct
     lamas mapping reject-fuzzy --orig "<orig_header>" --canonical "<correct one>"   # it's wrong
     lamas mapping reject-fuzzy --orig "<orig_header>"            # it's actually a new metric
     ```
   - For each `unresolved` row (no fuzzy candidate cleared the threshold): decide whether it's a
     variant of an existing canonical (search `data/header_mapping.yaml` for similar text) or a
     genuinely new metric, then:
     ```bash
     lamas mapping add --canonical "<existing or new canonical>" --orig "<orig_header>"
     ```
   Never accept a fuzzy suggestion, and never create a new canonical, purely because "nothing
   better turned up" - a wrong merge or an unnecessary new canonical is exactly the kind of
   fragmentation this whole mapping system exists to prevent.

5. **Confirm the year is clean.**
   ```bash
   lamas map-headers --year 2025 --strict
   ```
   Exits non-zero if anything is still unresolved - go back to step 4 if so.

6. **Regenerate stats and build the final output.**
   ```bash
   lamas stats
   lamas build --strict
   ```

7. **Run the full QA suite.**
   ```bash
   lamas qa
   ```
   This checks the whole historical dataset, not just the new year - a bad `sheet_config.yaml`
   tweak or a wrong mapping decision can regress older years too.

8. **Hand off to Postgres - only when asked.**
   ```bash
   lamas build --output local,postgres
   ```
   This is a shared-system write. Treat it as a suggestion to make to whoever's driving, not
   something to run automatically once QA passes.
