import os

from django.db import connection


def test_postgresql_connection_and_target_version(transactional_db):
    with connection.cursor() as cursor:
        cursor.execute("SHOW server_version_num")
        version = int(cursor.fetchone()[0])
    assert version >= 140000
    if os.environ.get("REQUIRE_PG18") == "1":
        assert 180000 <= version < 190000, f"Expected PostgreSQL 18, got {version}"
