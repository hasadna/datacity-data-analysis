import os
import re
import subprocess
from pathlib import Path

TABLE_IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


class PostgresNotConfiguredError(Exception):
    pass


def push_csv_to_postgres(csv_path, table='lamas_muni', truncate=True, engine=None):
    """Push an already-built CSV file (see `write_local` / `lamas build --output local`) into
    Postgres via `psql \\copy` - simpler than staging the whole dataset through dataflows'
    dump_to_sql, and matches how a human would do this by hand. `truncate=True` (the default)
    replaces the table's contents, matching the previous dump_to_sql(mode='rewrite') behavior -
    otherwise re-running this would just keep appending duplicate rows."""
    if not TABLE_IDENTIFIER.match(table):
        raise ValueError(f'Invalid table name: {table!r}')
    engine = engine or os.environ.get('DATAFLOWS_DB_ENGINE')
    if not engine:
        raise PostgresNotConfiguredError('DATAFLOWS_DB_ENGINE is not set - cannot write to Postgres')
    csv_path = str(Path(csv_path).resolve())
    escaped_path = csv_path.replace("'", "''")
    commands = []
    if truncate:
        commands += ['-c', f'TRUNCATE TABLE {table};']
    commands += ['-c', f"\\copy {table} FROM '{escaped_path}' WITH (FORMAT csv, HEADER true)"]
    subprocess.run(['psql', engine, '-v', 'ON_ERROR_STOP=1', *commands], check=True)
