import dataflows as DF


def write_local(rows, out_dir):
    """Write the final dataset locally, same schema/format as today's db_bkp/res_1.csv."""
    dp, _ = DF.Flow(
        rows,
        DF.update_resource(-1, name='lamas'),
        DF.dump_to_path(str(out_dir)),
    ).process()
    return dp
