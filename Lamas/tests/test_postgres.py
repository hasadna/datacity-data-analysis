import pytest

from lamas.io.postgres import PostgresNotConfiguredError, push_csv_to_postgres


def test_raises_when_engine_not_configured(monkeypatch, tmp_path):
    monkeypatch.delenv('DATAFLOWS_DB_ENGINE', raising=False)
    csv_path = tmp_path / 'res_1.csv'
    csv_path.write_text('year,name\n2024,foo\n')
    with pytest.raises(PostgresNotConfiguredError):
        push_csv_to_postgres(str(csv_path))


def test_rejects_unsafe_table_name(tmp_path):
    csv_path = tmp_path / 'res_1.csv'
    csv_path.write_text('year,name\n2024,foo\n')
    with pytest.raises(ValueError):
        push_csv_to_postgres(str(csv_path), table='lamas_muni; DROP TABLE foo;', engine='postgresql://x')


def test_invokes_psql_with_truncate_and_copy(monkeypatch, tmp_path):
    csv_path = tmp_path / 'res_1.csv'
    csv_path.write_text('year,name\n2024,foo\n')
    calls = []
    monkeypatch.setattr('lamas.io.postgres.subprocess.run', lambda args, **kw: calls.append(args))

    push_csv_to_postgres(str(csv_path), table='lamas_muni', engine='postgresql://x')

    assert calls
    args = calls[0]
    assert args[0] == 'psql'
    assert args[1] == 'postgresql://x'
    joined = ' '.join(args)
    assert 'TRUNCATE TABLE lamas_muni;' in joined
    assert f"\\copy lamas_muni FROM '{csv_path.resolve()}' WITH (FORMAT csv, HEADER true)" in joined


def test_no_truncate_when_disabled(monkeypatch, tmp_path):
    csv_path = tmp_path / 'res_1.csv'
    csv_path.write_text('year,name\n2024,foo\n')
    calls = []
    monkeypatch.setattr('lamas.io.postgres.subprocess.run', lambda args, **kw: calls.append(args))

    push_csv_to_postgres(str(csv_path), table='lamas_muni', truncate=False, engine='postgresql://x')

    joined = ' '.join(calls[0])
    assert 'TRUNCATE' not in joined
    assert '\\copy lamas_muni FROM' in joined
