"""PostgreSQL data layer.

Holds the frozen dataset as an immutable snapshot, and gives the plans and
approvals the service produces somewhere to live that survives a restart.

Deliberately NOT the default read path. The application still loads its
planning inputs from the frozen CSVs, because `python run.py` is meant to be
one command with no network and no service to start first. This layer is
proven equivalent before anything is asked to depend on it -- see
`blockplan_db.verify`.

Nothing here is imported at application start. psycopg is an optional
dependency; a checkout without it runs exactly as before.
"""
from .connection import (  # noqa: F401
    DatabaseNotConfiguredError,
    connection_settings,
    database_url,
    is_configured,
)

__all__ = [
    "DatabaseNotConfiguredError",
    "connection_settings",
    "database_url",
    "is_configured",
]
