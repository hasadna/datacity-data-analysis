def specific_fixes():
    """Hardcoded, one-off municipality-name corrections. Kept as code, not config: these are
    historical data-quality patches (a merger and two spelling variants), not layout config."""

    def func(rows):
        for row in rows:
            name = row['name']
            year = row['year']
            if name == 'נוף הגליל' and year < 2001:
                # Nof HaGalil was formed by a later merger/rename; pre-2001 rows under this
                # name are spurious.
                continue
            if name == 'תל אביב -יפו':
                row['name'] = 'תל אביב-יפו'
            if name == 'הרצלייה':
                row['name'] = 'הרצליה'
            yield row
    return func
