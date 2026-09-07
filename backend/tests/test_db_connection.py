"""Connection settings: resolution, precedence, and keeping the password out.

No database is contacted here. These cover the part that is easy to get wrong
and expensive to discover later -- silently connecting to the wrong database,
or leaking a password into a log line.
"""
from __future__ import annotations

import pytest

from blockplan_db.connection import (
    DatabaseNotConfiguredError,
    connection_settings,
    database_url,
    is_configured,
)

URL = "postgresql://planner:s3cret@db.example:6543/blockplan_test"


def test_url_is_parsed_into_its_parts():
    s = connection_settings({"BLOCKPLAN_DATABASE_URL": URL})
    assert (s.host, s.port, s.user, s.database) == (
        "db.example", 6543, "planner", "blockplan_test",
    )


def test_url_wins_over_the_pg_variables():
    """One place decides. Mixing halves of two configurations is how you end up
    authenticating against one server and naming a database on another."""
    s = connection_settings({
        "BLOCKPLAN_DATABASE_URL": URL,
        "PGHOST": "somewhere.else", "PGDATABASE": "wrong",
    })
    assert s.host == "db.example"
    assert s.database == "blockplan_test"


def test_pg_variables_are_accepted_so_pgpass_keeps_working():
    """libpq's own variables mean a password need never be typed at all."""
    s = connection_settings({"PGHOST": "localhost", "PGPORT": "5432",
                             "PGUSER": "postgres", "PGDATABASE": "blockplan"})
    assert (s.host, s.port, s.user, s.database) == (
        "localhost", 5432, "postgres", "blockplan",
    )


def test_defaults_fill_only_what_is_missing():
    s = connection_settings({"PGUSER": "postgres"})
    assert (s.host, s.port, s.database) == ("localhost", 5432, "blockplan")


def test_url_without_a_database_falls_back_to_the_default_name():
    s = connection_settings({"BLOCKPLAN_DATABASE_URL": "postgresql://u@h:5432"})
    assert s.database == "blockplan"


# -- refusing to guess ------------------------------------------------------

def test_an_empty_environment_raises_rather_than_guessing():
    """Deliberately not defaulting to localhost/postgres/postgres.

    A guessed connection either fails with a confusing authentication error or,
    worse, succeeds against the wrong database.
    """
    with pytest.raises(DatabaseNotConfiguredError) as exc:
        connection_settings({})
    assert "BLOCKPLAN_DATABASE_URL" in str(exc.value)
    assert "PGHOST" in str(exc.value)


def test_a_non_postgres_url_is_rejected():
    with pytest.raises(DatabaseNotConfiguredError):
        connection_settings({"BLOCKPLAN_DATABASE_URL": "mysql://u:p@h/db"})


def test_a_non_numeric_port_is_reported_clearly():
    with pytest.raises(DatabaseNotConfiguredError) as exc:
        connection_settings({"PGHOST": "localhost", "PGPORT": "not-a-port"})
    assert "PGPORT" in str(exc.value)


def test_is_configured_reports_without_connecting():
    assert is_configured({"BLOCKPLAN_DATABASE_URL": URL}) is True
    assert is_configured({}) is False


# -- the password must not escape -------------------------------------------

def test_describe_and_repr_never_contain_the_password():
    """These are what end up in logs, error messages and test output."""
    s = connection_settings({"BLOCKPLAN_DATABASE_URL": URL})
    assert "s3cret" not in s.describe()
    assert "s3cret" not in repr(s)
    assert "s3cret" not in database_url({"BLOCKPLAN_DATABASE_URL": URL})
    # ...and the target is still identifiable, which is the point of describe()
    assert "db.example:6543/blockplan_test" in s.describe()


def test_conninfo_carries_the_password_because_libpq_needs_it():
    """The one accessor that does. Named so a reader knows not to log it."""
    s = connection_settings({"BLOCKPLAN_DATABASE_URL": URL})
    conninfo = s.to_conninfo()
    assert "password=s3cret" in conninfo
    assert "dbname=blockplan_test" in conninfo


def test_no_password_is_emitted_when_none_was_supplied():
    s = connection_settings({"PGHOST": "localhost", "PGUSER": "postgres"})
    assert "password=" not in s.to_conninfo()
