"""Where the database connection details come from.

Credentials are read from the environment and never from a file in this
repository. That is partly hygiene -- a checked-in password ends up in the
git history permanently -- and partly because this project is demonstrated on
machines that are not the one it was built on, so the connection has to be
configurable without editing code.

Two forms are accepted, in this order:

  BLOCKPLAN_DATABASE_URL=postgresql://user:pass@host:5432/blockplan
  or libpq's own PGHOST / PGPORT / PGUSER / PGPASSWORD / PGDATABASE

The second form means `.pgpass` and `PGSERVICE` keep working, so a password
need never be typed anywhere at all. Nothing here logs, prints or returns a
password: `describe()` exists specifically so diagnostics can be shown safely.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

URL_ENV = "BLOCKPLAN_DATABASE_URL"
DEFAULT_DATABASE = "blockplan"
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 5432


class DatabaseNotConfiguredError(RuntimeError):
    """No connection details in the environment.

    Raised rather than falling back to a guessed localhost/postgres/postgres,
    which would either fail with a confusing authentication error or -- worse
    -- quietly connect to the wrong database.
    """


@dataclass(frozen=True)
class ConnectionSettings:
    """Everything needed to connect, with the password kept out of repr()."""

    host: str
    port: int
    user: str | None
    database: str
    _password: str | None = None

    def describe(self) -> str:
        """Safe for logs and error messages: identifies the target, not the secret."""
        who = f"{self.user}@" if self.user else ""
        return f"postgresql://{who}{self.host}:{self.port}/{self.database}"

    def to_conninfo(self) -> str:
        """libpq connection string. Never log the result."""
        parts = [f"host={self.host}", f"port={self.port}", f"dbname={self.database}"]
        if self.user:
            parts.append(f"user={self.user}")
        if self._password:
            parts.append(f"password={self._password}")
        return " ".join(parts)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"ConnectionSettings({self.describe()})"


def _from_url(url: str) -> ConnectionSettings:
    parsed = urlparse(url)
    if parsed.scheme not in ("postgresql", "postgres"):
        raise DatabaseNotConfiguredError(
            f"{URL_ENV} must start with postgresql:// (got {parsed.scheme!r}://)"
        )
    database = (parsed.path or "").lstrip("/") or DEFAULT_DATABASE
    return ConnectionSettings(
        host=parsed.hostname or DEFAULT_HOST,
        port=parsed.port or DEFAULT_PORT,
        user=parsed.username,
        database=database,
        _password=parsed.password,
    )


def _from_pg_env(env: dict[str, str]) -> ConnectionSettings | None:
    """libpq's own variables. Present if ANY of them is set.

    PGPASSWORD is read but stays optional: with .pgpass or a trust rule there
    is no password to read, and that is the better setup.
    """
    keys = ("PGHOST", "PGPORT", "PGUSER", "PGDATABASE", "PGPASSWORD")
    if not any(env.get(k) for k in keys):
        return None
    port_raw = env.get("PGPORT") or str(DEFAULT_PORT)
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise DatabaseNotConfiguredError(f"PGPORT must be a number, got {port_raw!r}") from exc
    return ConnectionSettings(
        host=env.get("PGHOST") or DEFAULT_HOST,
        port=port,
        user=env.get("PGUSER"),
        database=env.get("PGDATABASE") or DEFAULT_DATABASE,
        _password=env.get("PGPASSWORD"),
    )


def connection_settings(env: dict[str, str] | None = None) -> ConnectionSettings:
    """Resolve connection details, or say precisely what is missing."""
    env = dict(os.environ if env is None else env)

    url = env.get(URL_ENV)
    if url:
        return _from_url(url)

    from_pg = _from_pg_env(env)
    if from_pg is not None:
        return from_pg

    raise DatabaseNotConfiguredError(
        "no database connection configured. Set either\n"
        f"  {URL_ENV}=postgresql://user:password@localhost:5432/{DEFAULT_DATABASE}\n"
        "or libpq's PGHOST / PGPORT / PGUSER / PGDATABASE (with PGPASSWORD or "
        "a .pgpass entry).\n"
        "Nothing in this repository stores a password."
    )


def is_configured(env: dict[str, str] | None = None) -> bool:
    """True if a connection could be attempted. Used to skip tests, not to connect."""
    try:
        connection_settings(env)
    except DatabaseNotConfiguredError:
        return False
    return True


def database_url(env: dict[str, str] | None = None) -> str:
    """The target, safe to print. Not a connection string -- no password."""
    return connection_settings(env).describe()


def connect(env: dict[str, str] | None = None, *, autocommit: bool = False):
    """Open a connection. psycopg is imported here, not at module import.

    Keeping the import local means `blockplan_db` can be imported -- and its
    settings tested -- in a checkout that never installed the driver, which is
    the state the application itself runs in.
    """
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise DatabaseNotConfiguredError(
            "psycopg is not installed. Install it with:\n"
            '  pip install "psycopg[binary]"'
        ) from exc

    settings = connection_settings(env)
    return psycopg.connect(settings.to_conninfo(), autocommit=autocommit)
