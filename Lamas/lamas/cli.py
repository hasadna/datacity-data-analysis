import csv
import logging
import subprocess
from pathlib import Path

import click
import dataflows as DF
import pandas as pd

from . import downloader as downloader_mod
from .diagnose import diagnose_year
from .headers.fix_years import fix_years
from .headers.mapping import DuplicateOrigHeaderError, HeaderMapping
from .headers.pending import resolve_headers, write_pending_report
from .headers.specific_fixes import specific_fixes
from .headers.value_fixes import value_fixes
from .io.local import write_local
from .io.postgres import PostgresNotConfiguredError, write_postgres
from .logging_config import setup_logging
from .sheet_config import SheetConfig
from .stats import compute_header_stats, write_stats_report

LAMAS_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SHEET_CONFIG = LAMAS_ROOT / 'data' / 'sheet_config.yaml'
DEFAULT_MAPPING = LAMAS_ROOT / 'data' / 'header_mapping.yaml'
DEFAULT_CHECKPOINT = LAMAS_ROOT / '.cache' / 'preprocessed.parquet'
DEFAULT_PENDING_REPORT = LAMAS_ROOT / 'reports' / 'pending_headers.csv'
DEFAULT_STATS_CSV = LAMAS_ROOT / 'reports' / 'header_stats.csv'
DEFAULT_STATS_MD = LAMAS_ROOT / 'reports' / 'header_stats.md'
DEFAULT_OUTPUT_DIR = LAMAS_ROOT / 'db_bkp'
DEFAULT_DOWNLOADS_DIR = LAMAS_ROOT / 'downloads'

logger = logging.getLogger(__name__)


@click.group()
@click.option('--log-level', default='INFO')
def main(log_level):
    setup_logging(getattr(logging, log_level.upper(), logging.INFO))


@main.command()
@click.option('--year', type=int, default=None, help='Download a single year; omit for all configured years.')
def download(year):
    """Download one year or all configured years."""
    DEFAULT_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    if year:
        path = downloader_mod.download_excel(year, str(DEFAULT_DOWNLOADS_DIR))
        click.echo(path)
    else:
        filenames = downloader_mod.download_all(str(DEFAULT_DOWNLOADS_DIR))
        for y, path in sorted(filenames.items()):
            click.echo(f'{y}: {path}')


def _find_year_file(year):
    for ext in ('xlsx', 'xls'):
        p = DEFAULT_DOWNLOADS_DIR / f'lamas-muni-{year}.{ext}'
        if p.exists():
            return p
    raise click.ClickException(f'No downloaded file found for year {year} in {DEFAULT_DOWNLOADS_DIR}')


def _all_year_files():
    filenames = {}
    for p in sorted(DEFAULT_DOWNLOADS_DIR.glob('lamas-muni-*.*')):
        year = int(p.stem.split('-')[-1])
        filenames[year] = str(p)
    return filenames


@main.command()
@click.option('--year', type=int, required=True)
@click.option('--sheet', default=None, help='Restrict to a single sheet name.')
def diagnose(year, sheet):
    """Dry-run parse of a year's workbook against the current sheet_config.yaml."""
    filename = _find_year_file(year)
    sheet_config = SheetConfig.load(DEFAULT_SHEET_CONFIG)
    results = diagnose_year(year, str(filename), sheet_config, sheet_filter=sheet)
    if not results:
        click.echo('No sheets found (below MIN_SIZE, or file unreadable).')
        return
    for r in results:
        click.echo(f"--- {r['sheet']} ({r['row_count']}x{r['col_count']}) ---")
        if r['skipped']:
            click.echo('  skip=True in sheet_config.yaml')
            continue
        if r['error']:
            click.echo(f"  ERROR: {r['error']}")
            continue
        click.echo(f"  config: {r['config']}")
        click.echo(f"  name column index: {r['name_idx']}, header count: {r['header_count']}")
        click.echo(f"  header preview: {r['header_preview']}")


@main.group('config')
def config_group():
    """Inspect / edit sheet_config.yaml."""


@config_group.command('show')
@click.option('--year', type=int, required=True)
def config_show(year):
    sheet_config = SheetConfig.load(DEFAULT_SHEET_CONFIG)
    sheets = sheet_config.years.get(year, {})
    if not sheets:
        click.echo(f'No overrides for {year}; defaults apply: {sheet_config.defaults}')
        return
    for sheet, cfg in sorted(sheets.items()):
        click.echo(f'{sheet}: {cfg}')


@config_group.command('set-sheet')
@click.option('--year', type=int, required=True)
@click.option('--sheet', required=True)
@click.option('--header-rows', type=int, default=None)
@click.option('--extend-top', type=int, default=None)
@click.option('--extend-bottom', type=int, default=None)
@click.option('--skip/--no-skip', default=None)
def config_set_sheet(year, sheet, header_rows, extend_top, extend_bottom, skip):
    """Create/update one sheet_config.yaml entry (validates + rewrites the file deterministically)."""
    sheet_config = SheetConfig.load(DEFAULT_SHEET_CONFIG)
    overrides = {}
    if header_rows is not None:
        overrides['header_rows'] = header_rows
    if extend_top is not None:
        overrides['extend_headers_top'] = extend_top
    if extend_bottom is not None:
        overrides['extend_headers_bottom'] = extend_bottom
    if skip is not None:
        overrides['skip'] = skip
    sheet_config.set_sheet(year, sheet, **overrides)
    sheet_config.save(DEFAULT_SHEET_CONFIG)
    click.echo(f'Updated {sheet!r} for {year}: {sheet_config.get(year, sheet)}')


def _rows_to_dataframe(rows):
    return pd.DataFrame(rows)


def _dataframe_to_rows(df):
    return df.where(pd.notnull(df), None).to_dict('records')


@main.command()
@click.option('--year', type=int, default=None)
@click.option('--checkpoint', type=click.Path(), default=str(DEFAULT_CHECKPOINT))
def preprocess(year, checkpoint):
    """Run preprocess_files() (all years or just --year), write a parquet checkpoint."""
    from .preprocess import preprocess_files

    sheet_config = SheetConfig.load(DEFAULT_SHEET_CONFIG)
    filenames = {year: str(_find_year_file(year))} if year else _all_year_files()
    rows = list(preprocess_files(filenames, sheet_config))
    df = _rows_to_dataframe(rows)
    checkpoint = Path(checkpoint)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(checkpoint)
    click.echo(f'Wrote {len(rows)} rows to {checkpoint}')


def _load_checkpoint(checkpoint):
    df = pd.read_parquet(checkpoint)
    return _dataframe_to_rows(df)


def _apply_fix_years(rows):
    return list(DF.Flow(rows, DF.set_type('value', type='any'), DF.validate(), fix_years()).results()[0][0])


@main.command('map-headers')
@click.option('--year', type=int, default=None)
@click.option('--checkpoint', type=click.Path(exists=True), default=str(DEFAULT_CHECKPOINT))
@click.option('--mapping', 'mapping_path', type=click.Path(), default=str(DEFAULT_MAPPING))
@click.option('--strict', is_flag=True)
def map_headers(year, checkpoint, mapping_path, strict):
    """Regenerate reports/pending_headers.csv (optionally scoped to one year)."""
    rows = _load_checkpoint(checkpoint)
    if year:
        rows = [r for r in rows if r['year'] == year]
    rows = _apply_fix_years(rows)
    mapping = HeaderMapping.load(mapping_path)
    _, pending = resolve_headers(rows, mapping)
    write_pending_report(pending, DEFAULT_PENDING_REPORT)
    unresolved = [p for p in pending.values() if p['status'] == 'unresolved']
    auto = [p for p in pending.values() if p['status'] == 'auto_resolved_needs_confirmation']
    click.echo(f'{len(unresolved)} unresolved, {len(auto)} auto-resolved needing confirmation')
    click.echo(f'Report written to {DEFAULT_PENDING_REPORT}')
    if strict and unresolved:
        raise SystemExit(1)


@main.group('mapping')
def mapping_group():
    """Edit header_mapping.yaml."""


@mapping_group.command('add')
@click.option('--canonical', required=True)
@click.option('--orig', 'orig_header', required=True)
@click.option('--mapping', 'mapping_path', type=click.Path(), default=str(DEFAULT_MAPPING))
def mapping_add(canonical, orig_header, mapping_path):
    """Append orig_header to a canonical (existing or brand new)."""
    mapping = HeaderMapping.load(mapping_path)
    try:
        mapping.add_mapping(canonical, orig_header)
    except DuplicateOrigHeaderError as e:
        raise click.ClickException(str(e))
    mapping.save(mapping_path)
    click.echo(f'Mapped {orig_header!r} -> {canonical!r}')


def _read_pending_row(orig_header):
    if not DEFAULT_PENDING_REPORT.exists():
        raise click.ClickException(f'{DEFAULT_PENDING_REPORT} does not exist - run `lamas map-headers` first')
    with DEFAULT_PENDING_REPORT.open(encoding='utf-8') as f:
        for row in csv.DictReader(f):
            if row['orig_header'] == orig_header:
                return row
    raise click.ClickException(f'{orig_header!r} not found in {DEFAULT_PENDING_REPORT}')


@mapping_group.command('confirm-fuzzy')
@click.option('--orig', 'orig_header', required=True)
@click.option('--mapping', 'mapping_path', type=click.Path(), default=str(DEFAULT_MAPPING))
def mapping_confirm_fuzzy(orig_header, mapping_path):
    """Accept the suggested canonical for an auto_resolved_needs_confirmation pending row."""
    row = _read_pending_row(orig_header)
    canonical = row['suggested_canonical']
    if not canonical:
        raise click.ClickException(f'{orig_header!r} has no suggested_canonical to confirm')
    mapping = HeaderMapping.load(mapping_path)
    mapping.add_mapping(canonical, orig_header)
    mapping.save(mapping_path)
    click.echo(f'Confirmed {orig_header!r} -> {canonical!r}')


@mapping_group.command('reject-fuzzy')
@click.option('--orig', 'orig_header', required=True)
@click.option('--canonical', default=None, help='Omit to make orig_header its own new canonical.')
@click.option('--mapping', 'mapping_path', type=click.Path(), default=str(DEFAULT_MAPPING))
def mapping_reject_fuzzy(orig_header, canonical, mapping_path):
    """Override an auto-resolved row: map to a different canonical, or un-merge it entirely."""
    canonical = canonical or orig_header
    mapping = HeaderMapping.load(mapping_path)
    mapping.add_mapping(canonical, orig_header)
    mapping.save(mapping_path)
    click.echo(f'Overrode {orig_header!r} -> {canonical!r}')


@main.command()
@click.option('--year', type=int, default=None)
@click.option('--checkpoint', type=click.Path(exists=True), default=str(DEFAULT_CHECKPOINT))
@click.option('--mapping', 'mapping_path', type=click.Path(), default=str(DEFAULT_MAPPING))
def stats(year, checkpoint, mapping_path):
    """Regenerate reports/header_stats.{csv,md} (local replacement for the Airtable Stats table).

    Computed on post-normalization headers (fix_years + mapping resolution applied), matching
    what the original Airtable "Stats" table reflected - not the raw pre-normalization headers.
    """
    rows = _load_checkpoint(checkpoint)
    if year:
        rows = [r for r in rows if r['year'] == year]
    rows = _apply_fix_years(rows)
    mapping = HeaderMapping.load(mapping_path)
    rows, _pending = resolve_headers(rows, mapping)
    known_years = range(downloader_mod.MIN_YEAR, downloader_mod.MAX_YEAR + 1)
    result = compute_header_stats(rows, known_years)
    write_stats_report(result, DEFAULT_STATS_CSV, DEFAULT_STATS_MD)
    click.echo(f'Wrote {DEFAULT_STATS_CSV} and {DEFAULT_STATS_MD}')


def build_final_rows(checkpoint, mapping_path):
    """Shared by `build` and the test suite: fix_years -> resolve_headers -> specific/value fixes."""
    rows = _load_checkpoint(checkpoint)
    rows = _apply_fix_years(rows)
    mapping = HeaderMapping.load(mapping_path)
    resolved_rows, pending = resolve_headers(rows, mapping)
    write_pending_report(pending, DEFAULT_PENDING_REPORT)
    resolved_rows = list(specific_fixes()(resolved_rows))
    resolved_rows = list(value_fixes()(resolved_rows))
    for row in resolved_rows:
        row.pop('sheet', None)  # internal-only; not part of the shipped schema
    unresolved = [p for p in pending.values() if p['status'] == 'unresolved']
    return resolved_rows, unresolved


@main.command()
@click.option('--checkpoint', type=click.Path(exists=True), default=str(DEFAULT_CHECKPOINT))
@click.option('--mapping', 'mapping_path', type=click.Path(), default=str(DEFAULT_MAPPING))
@click.option('--strict', is_flag=True)
@click.option('--output', default='local', help='Comma-separated: local,postgres')
@click.option('--output-dir', type=click.Path(), default=str(DEFAULT_OUTPUT_DIR))
def build(checkpoint, mapping_path, strict, output, output_dir):
    """Apply specific_fixes/value_fixes and write final output."""
    resolved_rows, unresolved = build_final_rows(checkpoint, mapping_path)
    if strict and unresolved:
        raise click.ClickException(
            f'{len(unresolved)} unresolved headers remain - refusing to build in --strict mode'
        )
    targets = [t.strip() for t in output.split(',') if t.strip()]
    if 'local' in targets:
        write_local(resolved_rows, output_dir)
        click.echo(f'Wrote local output to {output_dir}')
    if 'postgres' in targets:
        try:
            write_postgres(resolved_rows)
        except PostgresNotConfiguredError as e:
            raise click.ClickException(str(e))
        click.echo('Wrote to Postgres table lamas_muni')


@main.command('full-run')
@click.option('--year', type=int, default=None)
@click.option('--strict', is_flag=True)
@click.option('--output', default='local')
@click.pass_context
def full_run(ctx, year, strict, output):
    """download -> preprocess -> map-headers -> stats -> build, one shot."""
    ctx.invoke(download, year=year)
    ctx.invoke(preprocess, year=year)
    ctx.invoke(map_headers, year=year, strict=False)
    ctx.invoke(stats, year=year)
    ctx.invoke(build, strict=strict, output=output)


@main.command()
def qa():
    """Run the pytest quality-assurance suite (local replacement for eyeballing Airtable Stats)."""
    result = subprocess.run(['pytest', str(LAMAS_ROOT / 'tests')])
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
