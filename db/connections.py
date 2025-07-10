from __future__ import annotations

import os
import urllib.parse
from typing import Any

from dotenv import load_dotenv
import sqlalchemy
from sqlalchemy.engine import URL
from config import settings

Engine = Any  # runtime fallback for type hints
Connection = Any

# Ensure environment variables from .env are loaded like previous modules
load_dotenv()

_engines: dict[str, Engine] = {}


def build_mssql_url(conn_str: str) -> URL:
    """Return an SQLAlchemy URL for an ODBC connection string."""
    encoded = urllib.parse.quote_plus(conn_str)
    return URL.create("mssql+pyodbc", query={"odbc_connect": encoded})


def build_mysql_url(
    host: str,
    user: str,
    password: str,
    database: str,
    port: int = 3306,
) -> URL:
    """Return a MySQL connection URL using mysqlconnector."""
    return URL.create(
        "mysql+mysqlconnector",
        username=user,
        password=password,
        host=host,
        port=port,
        database=database,
    )


def get_engine(url: URL | str) -> Engine:
    """Return (and cache) a SQLAlchemy engine for ``url``."""
    key = str(url)
    engine = _engines.get(key)
    if engine is None:
        # Use default pool settings since they're not in the current settings class
        engine = sqlalchemy.create_engine(
            url,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
            pool_pre_ping=True,
        )
        _engines[key] = engine
    return engine


def get_connection(url: URL | str) -> Connection:
    """Return a pooled connection for ``url``."""
    return get_engine(url).connect()


def get_mssql_connection(conn_str: str) -> Connection:
    """Return a connection using an ODBC connection string."""
    return get_connection(build_mssql_url(conn_str))


def get_source_connection() -> Connection:
    """Connect to the configured MSSQL source database."""
    # Check environment variable first, then settings property
    conn_str = os.environ.get('MSSQL_SOURCE_CONN_STR') or settings.mssql_target_conn_str
    if not conn_str:
        raise ValueError("No source connection string configured")
    return get_mssql_connection(conn_str)


def get_target_connection() -> Connection:
    """Connect to the configured MSSQL target database."""
    # FIXED: Check environment variable first, then settings property
    conn_str = os.environ.get('MSSQL_TARGET_CONN_STR') or settings.mssql_target_conn_str
    if not conn_str:
        raise ValueError("No target connection string configured")
    return get_mssql_connection(conn_str)


def get_mysql_connection(
    host: str | None = None,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
    port: int | None = None,
) -> Connection:
    """Return a pooled MySQL connection using provided args or configuration."""
    host = host or os.getenv("MYSQL_HOST")
    user = user or os.getenv("MYSQL_USER") 
    password = password or os.getenv("MYSQL_PASSWORD")
    database = database or os.getenv("MYSQL_DATABASE")
    port_value = port or os.getenv("MYSQL_PORT") or 3306
    port = int(port_value)

    if not all([host, user, password, database]):
        raise ValueError("Missing required MySQL connection parameters.")

    return get_connection(build_mysql_url(host, user, password, database, port))


__all__ = [
    "build_mssql_url",
    "build_mysql_url",
    "get_engine",
    "get_connection",
    "get_mssql_connection",
    "get_source_connection",
    "get_target_connection",
    "get_mysql_connection",
]