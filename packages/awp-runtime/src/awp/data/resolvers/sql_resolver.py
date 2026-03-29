"""Resolver for SQL query sources."""

from __future__ import annotations

import logging
import re
from typing import Any

from awp.data.sources import ResolverResult, Source

logger = logging.getLogger(__name__)


def _substitute_secrets(dsn: str, secrets: dict[str, str]) -> str:
    """Replace ``$SECRET_NAME`` patterns in the DSN string."""
    return re.sub(
        r"\$([A-Z_][A-Z0-9_]*)",
        lambda m: secrets.get(m.group(1), m.group(0)),
        dsn,
    )


def _rows_to_dicts(cursor: Any) -> list[dict[str, Any]]:
    """Convert cursor rows to a list of dicts using column descriptions."""
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


class SqlResolver:
    """Resolve ``kind='sql'`` sources against SQLite or SQLAlchemy-supported databases."""

    def can_handle(self, source: Source) -> bool:
        return source.kind == "sql"

    def resolve(self, source: Source, secrets: dict[str, str] | None = None) -> ResolverResult:
        secrets = secrets or {}
        dsn: str = source.params.get("dsn", "")
        dsn = _substitute_secrets(dsn, secrets)
        query = source.uri
        query_params = source.params.get("query_params")

        if dsn.startswith("sqlite://"):
            return self._resolve_sqlite(query, dsn, query_params, source.format)
        return self._resolve_sqlalchemy(query, dsn, query_params, source.format)

    def _resolve_sqlite(
        self,
        query: str,
        dsn: str,
        query_params: dict[str, Any] | None,
        fmt: str | None,
    ) -> ResolverResult:
        import sqlite3

        # sqlite:///path or sqlite:////abs/path
        db_path = dsn.replace("sqlite:///", "", 1) or ":memory:"
        logger.info("Executing SQLite query on %s", db_path)

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute(query, query_params or ())
            rows = _rows_to_dicts(cursor)
            row_count = len(rows)
        finally:
            conn.close()

        data = self._format_rows(rows, fmt)
        metadata: dict[str, Any] = {
            "source_kind": "sql",
            "dsn": dsn,
            "row_count": row_count,
            "format": fmt or "list_of_dicts",
            "engine": "sqlite3",
        }
        return ResolverResult(data=data, metadata=metadata)

    def _resolve_sqlalchemy(
        self,
        query: str,
        dsn: str,
        query_params: dict[str, Any] | None,
        fmt: str | None,
    ) -> ResolverResult:
        try:
            import sqlalchemy
        except ImportError:
            raise ImportError(
                "sqlalchemy is required for non-SQLite databases. "
                "Install with: pip install sqlalchemy"
            )

        logger.info("Executing SQL query via SQLAlchemy")
        engine = sqlalchemy.create_engine(dsn)
        with engine.connect() as conn:
            result = conn.execute(sqlalchemy.text(query), query_params or {})
            columns = list(result.keys())
            rows = [dict(zip(columns, row)) for row in result.fetchall()]
            row_count = len(rows)

        data = self._format_rows(rows, fmt)
        metadata: dict[str, Any] = {
            "source_kind": "sql",
            "dsn": dsn,
            "row_count": row_count,
            "format": fmt or "list_of_dicts",
            "engine": "sqlalchemy",
        }
        return ResolverResult(data=data, metadata=metadata)

    @staticmethod
    def _format_rows(rows: list[dict[str, Any]], fmt: str | None) -> Any:
        """Convert row dicts to the requested format."""
        if fmt == "dataframe" or fmt is None:
            try:
                import pandas as pd
                return pd.DataFrame(rows)
            except ImportError:
                logger.debug("pandas not available; returning list of dicts")
                return rows
        return rows
