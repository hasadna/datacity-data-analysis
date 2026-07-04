import os

import dataflows as DF


class PostgresNotConfiguredError(Exception):
    pass


def write_postgres(rows, table='lamas_muni', mode='rewrite'):
    """Write the final dataset to Postgres. This formalizes the DF.dump_to_sql(...) call that was
    commented out in the original notebook - it is only ever invoked when the user explicitly
    asks for `--output postgres`, never by default."""
    engine = os.environ.get('DATAFLOWS_DB_ENGINE')
    if not engine:
        raise PostgresNotConfiguredError('DATAFLOWS_DB_ENGINE is not set - cannot write to Postgres')
    DF.Flow(
        rows,
        DF.update_resource(-1, name='lamas'),
        DF.dump_to_sql({
            table: {
                'resource-name': 'lamas',
                'mode': mode,
            }
        }, engine=engine, batch_size=1000),
    ).process()
