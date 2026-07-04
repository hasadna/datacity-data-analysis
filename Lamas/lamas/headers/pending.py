import csv
import logging
from pathlib import Path

import dataflows as DF
import pandas as pd

from .fix_years import fix_years
from .fuzzy import AUTO_MERGE_THRESHOLD, SUGGESTION_THRESHOLD, best_match
from .mapping import HeaderMapping

logger = logging.getLogger(__name__)

PENDING_FIELDS = [
    'orig_header', 'status', 'suggested_canonical', 'suggested_score',
    'count', 'years', 'sheets', 'sample_values',
]


def real_header_universe(checkpoint_path):
    """The set of headers actually produced by preprocessing our own downloaded workbooks, post
    fix_years - the authoritative filter for "is this orig_header actually needed" (used both to
    seed header_mapping.yaml and by the QA suite to catch stale/unused mapping entries)."""
    df = pd.read_parquet(checkpoint_path)
    rows = df.where(pd.notnull(df), None).to_dict('records')
    rows = list(DF.Flow(rows, DF.set_type('value', type='any'), DF.validate(), fix_years()).results()[0][0])
    return set(r['header'] for r in rows)


def final_headers_by_year(checkpoint_path, mapping: HeaderMapping):
    """Per-year set of FINAL (mapped-to-canonical) headers actually produced by the pipeline.
    Used to check year-over-year header coverage - e.g. "did a header that was reported every
    year for a while suddenly go missing", which is exactly the class of silent extraction bug
    found during 2023/2024 ingestion (a whole section's worth of headers disappearing)."""
    df = pd.read_parquet(checkpoint_path)
    rows = df.where(pd.notnull(df), None).to_dict('records')
    rows = list(DF.Flow(rows, DF.set_type('value', type='any'), DF.validate(), fix_years()).results()[0][0])
    by_year = {}
    for row in rows:
        canonical = mapping.resolve(row['header']) or row['header']
        by_year.setdefault(row['year'], set()).add(canonical)
    return by_year


def resolve_headers(rows, mapping: HeaderMapping):
    """Resolve each row's header against `mapping`.

    For each row's orig_header:
      1. exact match in the mapping -> resolved, no pending entry.
      2. no exact match -> fuzzy-compare against the mapping's *known* orig_headers (a stable,
         human-curated reference set - not against other unmapped headers as the old
         self-clustering translate_headers() did). Score > AUTO_MERGE_THRESHOLD -> auto-resolve
         AND record it as 'auto_resolved_needs_confirmation' (visible, unlike the old silent
         auto-merge). Otherwise -> 'unresolved', header left unchanged.

    Returns (resolved_rows, pending_by_orig) where pending_by_orig aggregates count/years/sheets/
    sample_values per distinct orig_header, for the pending report.
    """
    known_origs = mapping.known_orig_headers()
    aggregates = {}
    resolved_rows = []
    fuzzy_cache = {}

    for row in rows:
        orig_header = row['header']
        row['orig_header'] = orig_header
        canonical = mapping.resolve(orig_header)
        status = None
        suggestion = None
        score = None

        if canonical is not None:
            row['header'] = canonical
        else:
            if orig_header not in fuzzy_cache:
                fuzzy_cache[orig_header] = best_match(orig_header, known_origs)
            suggestion_orig, score = fuzzy_cache[orig_header]
            suggestion = mapping.resolve(suggestion_orig) if suggestion_orig else None
            if suggestion and score is not None and score > AUTO_MERGE_THRESHOLD:
                row['header'] = suggestion
                status = 'auto_resolved_needs_confirmation'
            else:
                status = 'unresolved'
                if not suggestion or score is None or score <= SUGGESTION_THRESHOLD:
                    suggestion, score = None, None

        resolved_rows.append(row)

        if status is not None:
            agg = aggregates.setdefault(orig_header, {
                'orig_header': orig_header,
                'status': status,
                'suggested_canonical': suggestion,
                'suggested_score': score,
                'count': 0,
                'years': set(),
                'sheets': set(),
                'sample_values': [],
            })
            agg['count'] += 1
            if row.get('year') is not None:
                agg['years'].add(row['year'])
            if row.get('sheet'):
                agg['sheets'].add(row['sheet'])
            if row.get('value') and len(agg['sample_values']) < 5:
                agg['sample_values'].append(str(row['value']))

    return resolved_rows, aggregates


def write_pending_report(aggregates: dict, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(aggregates.values(), key=lambda a: (-a['count'], a['orig_header']))
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=PENDING_FIELDS)
        writer.writeheader()
        for agg in rows:
            writer.writerow({
                'orig_header': agg['orig_header'],
                'status': agg['status'],
                'suggested_canonical': agg['suggested_canonical'] or '',
                'suggested_score': agg['suggested_score'] if agg['suggested_score'] is not None else '',
                'count': agg['count'],
                'years': ','.join(str(y) for y in sorted(agg['years'])),
                'sheets': ','.join(sorted(agg['sheets'])),
                'sample_values': '|'.join(agg['sample_values']),
            })
    logger.info('Wrote %d pending header entries to %s', len(rows), path)
