"""Supabase PostgreSQL-backed persistence for the legacy SQLite application.

This compatibility bridge stores a compressed SQLite snapshot in a PostgreSQL BYTEA
row. It provides cloud persistence and optimistic concurrency detection, but it is
NOT a normalized, concurrent multi-writer data model. Run one desktop writer at a
time until the application tables are migrated to native PostgreSQL repositories.
"""
from __future__ import annotations

import gzip
import os
import sqlite3
import tempfile
import threading
from pathlib import Path

try:
    import psycopg
except Exception:  # provide a clear setup error if dependency is absent
    psycopg = None

APP_ID = os.getenv("GOVAI_CLOUD_APP_ID", "government-ai-platform")
_lock = threading.RLock()
_revision: int | None = None
_last_error = ""
_restore_done = False
_last_local_sig = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS public.platform_snapshots (
    app_id TEXT PRIMARY KEY,
    revision BIGINT NOT NULL DEFAULT 0,
    db_gzip BYTEA NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by TEXT
);
"""


def _connect(database_url: str):
    if not psycopg:
        raise RuntimeError("psycopg is missing. Install requirements.txt first.")
    if not database_url:
        raise RuntimeError("SUPABASE_DB_URL is not configured.")
    return psycopg.connect(database_url, connect_timeout=15, sslmode="require")


def _local_sig(db_path: str):
    values = []
    for candidate in (db_path, db_path + "-wal"):
        try:
            st = os.stat(candidate)
            values.append((st.st_mtime_ns, st.st_size))
        except OSError:
            values.append(None)
    return tuple(values)


def _snapshot(db_path: str) -> bytes:
    src = sqlite3.connect(db_path)
    fd, temp_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    try:
        dst = sqlite3.connect(temp_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
        return gzip.compress(Path(temp_path).read_bytes(), compresslevel=6)
    finally:
        src.close()
        try:
            os.remove(temp_path)
        except OSError:
            pass


def _valid_snapshot(blob: bytes) -> str:
    raw = gzip.decompress(blob)
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        conn = sqlite3.connect(path)
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Cloud database snapshot failed SQLite integrity_check.")
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "app_users" not in tables or "audit_logs" not in tables:
                raise ValueError("Cloud snapshot is missing required Government AI tables.")
        finally:
            conn.close()
        return path
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        raise


def initialize(database_url: str) -> None:
    # Schema is provisioned once by the project owner using supabase/001_platform_snapshots.sql.
    with _connect(database_url) as conn:
        conn.execute("SELECT 1 FROM public.platform_snapshots LIMIT 1")


def restore_if_available(database_url: str, db_path: str) -> dict:
    """Restore cloud snapshot at startup; if none exists, caller initializes SQLite."""
    global _revision, _last_error, _restore_done, _last_local_sig
    if not database_url:
        return {"configured": False, "restored": False, "message": "Cloud database is not configured."}
    with _lock:
        if _restore_done:
            return {"configured": True, "restored": False, "revision": _revision, "message": "Cloud database already initialized for this app process."}
        try:
            initialize(database_url)
            with _connect(database_url) as conn:
                row = conn.execute(
                    "SELECT revision, db_gzip FROM public.platform_snapshots WHERE app_id=%s",
                    (APP_ID,),
                ).fetchone()
            if not row:
                _revision = 0
                _restore_done = True
                return {"configured": True, "restored": False, "message": "No cloud snapshot exists yet; first save will initialize it."}
            revision, blob = row
            temp_path = _valid_snapshot(bytes(blob))
            try:
                src = sqlite3.connect(temp_path)
                dst = sqlite3.connect(db_path)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
                    src.close()
            finally:
                os.remove(temp_path)
            _revision = int(revision)
            _restore_done = True
            _last_local_sig = _local_sig(db_path)
            _last_error = ""
            return {"configured": True, "restored": True, "revision": _revision, "message": f"Restored cloud database revision {_revision}."}
        except Exception as exc:
            _last_error = str(exc)
            _restore_done = False
            return {"configured": True, "restored": False, "error": _last_error, "message": f"Cloud restore failed: {_last_error}"}


def save_database(database_url: str, db_path: str, username: str = "desktop", force: bool = False) -> dict:
    """Upload a snapshot only if its previously-read revision is still current."""
    global _revision, _last_error, _last_local_sig
    if not database_url:
        return {"saved": False, "configured": False, "message": "Cloud database is not configured."}
    with _lock:
        try:
            sig = _local_sig(db_path)
            if not force and _last_local_sig == sig:
                return {"saved": False, "unchanged": True, "revision": _revision, "message": "No local database changes to sync."}
            initialize(database_url)
            blob = _snapshot(db_path)
            expected = _revision
            with _connect(database_url) as conn:
                if expected is None:
                    row = conn.execute(
                        "SELECT revision FROM public.platform_snapshots WHERE app_id=%s", (APP_ID,)
                    ).fetchone()
                    expected = int(row[0]) if row else 0
                if expected == 0:
                    result = conn.execute(
                        "INSERT INTO public.platform_snapshots(app_id,revision,db_gzip,updated_by) "
                        "VALUES (%s,1,%s,%s) ON CONFLICT(app_id) DO NOTHING RETURNING revision",
                        (APP_ID, blob, username[:120]),
                    ).fetchone()
                else:
                    result = conn.execute(
                        "UPDATE public.platform_snapshots SET revision=revision+1, db_gzip=%s, "
                        "updated_at=NOW(), updated_by=%s WHERE app_id=%s AND revision=%s RETURNING revision",
                        (blob, username[:120], APP_ID, expected),
                    ).fetchone()
                if not result:
                    raise RuntimeError("Cloud database conflict: another desktop instance saved a newer revision. Reload the cloud database before saving again.")
                _revision = int(result[0])
            _last_local_sig = _local_sig(db_path)
            _last_error = ""
            return {"saved": True, "revision": _revision, "message": f"Cloud database saved (revision {_revision})."}
        except Exception as exc:
            _last_error = str(exc)
            return {"saved": False, "error": _last_error, "message": f"Cloud save failed: {_last_error}"}


def status() -> dict:
    return {"revision": _revision, "last_error": _last_error}
