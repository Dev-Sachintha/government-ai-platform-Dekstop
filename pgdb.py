"""Database access layer.

* SUPABASE_DB_URL (or DATABASE_URL) set  -> Supabase PostgreSQL through a connection pool.
* not set                                -> the local SQLite file (development / offline mode).

The rest of the app keeps using the small sqlite3-style API it always used
(connect / execute / cursor / fetch* / commit / close / lastrowid, `?` placeholders);
this module translates those calls to PostgreSQL. No Streamlit calls here.
"""
from __future__ import annotations

import decimal
import os
import re
import sqlite3
import threading

try:  # PostgreSQL driver is optional in local SQLite mode
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None

# --------------------------------------------------------------------------- config
def database_url() -> str:
    return (os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL") or "").strip()


def is_postgres() -> bool:
    return bool(database_url())


# Exception types usable in `except pgdb.Error:` in both modes.
Error = (sqlite3.Error, psycopg.Error) if psycopg else sqlite3.Error
IntegrityError = (sqlite3.IntegrityError, psycopg.IntegrityError) if psycopg else sqlite3.IntegrityError
# Assign this to conn.row_factory (ignored in PostgreSQL mode: rows always support r[0] and r["col"]).
Row = sqlite3.Row

# Tables whose primary key is an identity column called `id` (INSERT ... RETURNING id -> lastrowid).
IDENTITY_TABLES = {
    "government_services", "audit_logs", "app_users", "web_sources", "web_pages",
    "library_files", "library_items", "scan_items", "chat_messages",
}

# CURRENT_TIMESTAMP in the original code wrote 'YYYY-MM-DD HH:MM:SS' text; keep that format.
NOW_TEXT = "to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD HH24:MI:SS')"


# --------------------------------------------------------------------------- SQL translation
_STRING = re.compile(r"('(?:[^']|'')*')")
_DDL = re.compile(r"^\s*(CREATE\s+(UNIQUE\s+)?(TABLE|INDEX)|ALTER\s+TABLE|DROP\s+TABLE)\b", re.I)
_PRAGMA = re.compile(r"^\s*PRAGMA\b", re.I)
_INSERT_TABLE = re.compile(r"^\s*INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)", re.I)
_OR_CLAUSE = re.compile(r"\bINSERT\s+OR\s+(IGNORE|REPLACE)\b", re.I)


def _code_segment(seg: str, has_params: bool) -> str:
    seg = re.sub(r"([\w.]+)\s*=\s*\?\s+COLLATE\s+NOCASE", r"lower(\1) = lower(?)", seg, flags=re.I)
    seg = re.sub(r"([\w.]+)\s+COLLATE\s+NOCASE", r"lower(\1)", seg, flags=re.I)
    seg = re.sub(r"\bCURRENT_TIMESTAMP\b", NOW_TEXT, seg, flags=re.I)
    seg = re.sub(r"\bLIKE\s+\?", "ILIKE ? ESCAPE ''", seg, flags=re.I)   # SQLite LIKE is case-insensitive
    seg = re.sub(r"\bLIKE\b", "ILIKE", seg, flags=re.I)
    if has_params:
        seg = seg.replace("%", "%%")
    return seg.replace("?", "%s")


def translate(sql: str, has_params: bool = True, returning_id: bool = True):
    """SQLite-flavoured SQL -> (PostgreSQL SQL | None, appended_returning).

    None means "nothing to run" (DDL and PRAGMA are handled by the Supabase schema)."""
    if _DDL.match(sql) or _PRAGMA.match(sql):
        return None, False
    if _OR_CLAUSE.search(sql):
        raise NotImplementedError("INSERT OR IGNORE/REPLACE must be written as ON CONFLICT for PostgreSQL")
    parts = _STRING.split(sql)
    out = []
    for i, part in enumerate(parts):
        if i % 2:   # string literal
            out.append(part.replace("%", "%%") if has_params else part)
        else:
            out.append(_code_segment(part, has_params))
    pg = "".join(out).strip().rstrip(";").rstrip()
    appended = False
    m = _INSERT_TABLE.match(pg)
    if returning_id and m and m.group(1).lower() in IDENTITY_TABLES and not re.search(r"\bRETURNING\b", pg, re.I):
        pg += " RETURNING id"
        appended = True
    return pg, appended


def split_script(script: str) -> list[str]:
    stmts, buf = [], []
    for i, part in enumerate(_STRING.split(script)):
        if i % 2:
            buf.append(part)
            continue
        pieces = part.split(";")
        for j, piece in enumerate(pieces):
            buf.append(piece)
            if j < len(pieces) - 1:
                stmts.append("".join(buf).strip())
                buf = []
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return [s for s in stmts if s]


# --------------------------------------------------------------------------- rows / params
class PgRow(tuple):
    """tuple that also supports row["column"], keys() and dict(row) (like sqlite3.Row)."""

    def __new__(cls, keys, values):
        obj = super().__new__(cls, values)
        obj._keys = tuple(keys)
        return obj

    def keys(self):
        return list(self._keys)

    def __getitem__(self, item):
        if isinstance(item, str):
            return super().__getitem__(self._keys.index(item.lower()))
        return super().__getitem__(item)


def _convert_value(v):
    if isinstance(v, decimal.Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, memoryview):
        return bytes(v)
    return v


def _row_factory(cursor):
    cols = [d.name for d in (cursor.description or [])]

    def make(values):
        return PgRow(cols, [_convert_value(v) for v in values])

    return make


def _clean_param(v):
    if isinstance(v, str):
        return v.replace("\x00", "")        # PostgreSQL text cannot hold NUL (PDF extraction can produce it)
    if isinstance(v, (bytearray, memoryview)):
        return bytes(v)
    if type(v).__module__ == "numpy" and hasattr(v, "item"):
        return v.item()
    return v


def _clean_params(params):
    if params is None:
        return None
    return tuple(_clean_param(p) for p in params)


# --------------------------------------------------------------------------- connection pool
_pool = None
_pool_lock = threading.Lock()
_schema_done = False


def _normalized_url() -> str:
    url = database_url()
    if "sslmode=" not in url and "localhost" not in url and "127.0.0.1" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def _get_pool():
    global _pool
    if psycopg is None:
        raise RuntimeError("SUPABASE_DB_URL is set but the 'psycopg' package is missing (pip install 'psycopg[binary]' psycopg_pool).")
    with _pool_lock:
        if _pool is None:
            from psycopg_pool import ConnectionPool

            _pool = ConnectionPool(
                _normalized_url(),
                min_size=1,
                max_size=int(os.environ.get("GOVAI_DB_POOL_MAX", "8")),
                timeout=30,
                kwargs={"prepare_threshold": None, "connect_timeout": 15},   # works with Supabase's pooler
                check=ConnectionPool.check_connection,
                open=True,
            )
    return _pool


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


def ensure_schema() -> None:
    """Create / upgrade the Supabase tables once per process (idempotent)."""
    global _schema_done
    if _schema_done or not is_postgres():
        return
    if os.environ.get("GOVAI_SKIP_SCHEMA", "").strip() == "1":   # restricted login role: schema applied by an admin
        _schema_done = True
        return
    with _pool_lock:
        if _schema_done:
            return
    from pg_schema import CORE_SQL, ROLES_SQL

    pool = _get_pool()
    with pool.connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(727274)")
        conn.execute(CORE_SQL)
    try:  # read-only roles for the AI/workbench SQL; failing here must not stop the app
        with pool.connection() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(727274)")
            conn.execute(ROLES_SQL)
    except Exception as exc:  # noqa: BLE001
        print(f"[pgdb] could not create read-only SQL roles ({exc}); AI/workbench SQL stays disabled.")
    _schema_done = True


# --------------------------------------------------------------------------- sqlite3-style wrappers
class PgCursor:
    def __init__(self, owner: "PgConnection"):
        self._owner = owner
        self._c = owner._conn.cursor(row_factory=_row_factory)
        self.lastrowid = None
        self.rowcount = -1

    @property
    def description(self):
        return self._c.description

    def _run(self, fn, *args):
        try:
            return fn(*args)
        except psycopg.Error:
            self._owner._conn.rollback()    # PostgreSQL aborts the whole transaction on error
            raise

    def execute(self, sql, params=None):
        has_params = params is not None and len(params) > 0
        pg, appended = translate(sql, has_params)
        if pg is None:
            return self
        self._run(self._c.execute, pg, _clean_params(params) if has_params else None)
        self.rowcount = self._c.rowcount
        if appended and self._c.description:
            row = self._c.fetchone()
            self.lastrowid = row[0] if row else None
        return self

    def executemany(self, sql, seq):
        pg, _ = translate(sql, True, returning_id=False)
        if pg is None:
            return self
        self._run(self._c.executemany, pg, [_clean_params(p) for p in seq])
        self.rowcount = self._c.rowcount
        return self

    def executescript(self, script):
        for stmt in split_script(script):
            self.execute(stmt)
        return self

    def fetchone(self):
        return self._c.fetchone() if self._c.description else None

    def fetchall(self):
        return self._c.fetchall() if self._c.description else []

    def fetchmany(self, size=1):
        return self._c.fetchmany(size) if self._c.description else []

    def __iter__(self):
        return iter(self.fetchall())

    def close(self):
        self._c.close()


class PgConnection:
    def __init__(self):
        ensure_schema()
        self._pool = _get_pool()
        self._conn = self._pool.getconn()
        self._closed = False
        self.row_factory = None    # accepted for sqlite3 compatibility; rows are always PgRow

    def cursor(self):
        return PgCursor(self)

    def execute(self, sql, params=None):
        return self.cursor().execute(sql, params)

    def executemany(self, sql, seq):
        return self.cursor().executemany(sql, seq)

    def executescript(self, script):
        return self.cursor().executescript(script)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        self._pool.putconn(self._conn)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False


def connect(db_path: str = "database.db"):
    """Drop-in replacement for sqlite3.connect(db_path)."""
    if is_postgres():
        return PgConnection()
    return sqlite3.connect(db_path)


# --------------------------------------------------------------------------- restricted read-only SQL
READ_ROLES = {"chat": "govai_chat_ro", "workbench": "govai_workbench_ro"}


def read_df(db_path: str, sql: str, scope: str = "workbench", timeout_ms: int = 10000, max_rows: int = 5000):
    """Run an untrusted SELECT (AI-written or typed by an admin) and return a DataFrame.

    PostgreSQL: read-only transaction, statement timeout, row cap, and a database role
    that can only see the tables/columns allowed for `scope`."""
    import pandas as pd

    if not is_postgres():
        conn = sqlite3.connect(db_path)
        try:
            return pd.read_sql_query(sql, conn)
        finally:
            conn.close()

    ensure_schema()
    role = READ_ROLES[scope]
    pool = _get_pool()
    with pool.connection() as conn:
        try:
            conn.execute("SET TRANSACTION READ ONLY")
            conn.execute(f"SET LOCAL ROLE {role}")
            conn.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
            cur = conn.execute(sql)          # no params: '%' in LIKE patterns is literal
            cols = [d.name for d in (cur.description or [])]
            rows = cur.fetchmany(max_rows) if cols else []
            return pd.DataFrame([[_convert_value(v) for v in r] for r in rows], columns=cols)
        finally:
            conn.rollback()


def table_columns(db_path: str, hidden_tables=(), hidden_columns=()) -> list[tuple[str, str, str]]:
    """[(table, column, type)] for tables the AI may see (PostgreSQL or SQLite)."""
    conn = connect(db_path)
    try:
        out = []
        if is_postgres():
            rows = conn.execute(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' ORDER BY table_name, ordinal_position"
            ).fetchall()
            out = [(r[0], r[1], r[2]) for r in rows]
        else:
            names = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
            for t in names:
                for c in conn.execute(f'PRAGMA table_info("{t}")').fetchall():
                    out.append((t, c[1], c[2]))
        return [r for r in out if r[0] not in hidden_tables and (r[0], r[1]) not in hidden_columns]
    finally:
        conn.close()
