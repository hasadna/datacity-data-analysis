import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

STATS_FIELDS = ['header', 'count', 'years', 'min_year', 'max_year', 'expected_years_missing']


def compute_header_stats(rows, known_years=None):
    """Local replacement for the Airtable "Stats" table: per-header count/year-coverage,
    plus a derived `expected_years_missing` column flagging gaps within a header's own span."""
    per_header = {}
    for row in rows:
        h = row['header']
        agg = per_header.setdefault(h, {'count': 0, 'years': set()})
        agg['count'] += 1
        agg['years'].add(row['year'])

    known_years = sorted(set(known_years or []))
    results = []
    for header, agg in per_header.items():
        years = sorted(agg['years'])
        missing = [
            y for y in known_years
            if years and years[0] <= y <= years[-1] and y not in agg['years']
        ]
        results.append({
            'header': header,
            'count': agg['count'],
            'years': years,
            'min_year': years[0] if years else None,
            'max_year': years[-1] if years else None,
            'expected_years_missing': missing,
        })
    return results


def write_stats_report(stats, csv_path, md_path):
    csv_path = Path(csv_path)
    md_path = Path(md_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(stats, key=lambda s: s['count'])

    with csv_path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=STATS_FIELDS)
        writer.writeheader()
        for s in ordered:
            writer.writerow({
                'header': s['header'],
                'count': s['count'],
                'years': ','.join(str(y) for y in s['years']),
                'min_year': s['min_year'],
                'max_year': s['max_year'],
                'expected_years_missing': ','.join(str(y) for y in s['expected_years_missing']),
            })

    lines = [
        '| header | count | min_year | max_year | expected_years_missing |',
        '|---|---|---|---|---|',
    ]
    for s in ordered:
        lines.append(
            f"| {s['header']} | {s['count']} | {s['min_year']} | {s['max_year']} | "
            f"{','.join(str(y) for y in s['expected_years_missing'])} |"
        )
    md_path.write_text('\n'.join(lines), encoding='utf-8')
    logger.info('Wrote %d header stats rows to %s and %s', len(ordered), csv_path, md_path)
