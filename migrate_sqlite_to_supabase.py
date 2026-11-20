"""One-time copy of an existing local SQLite database (database.db) into Supabase PostgreSQL.

    python migrate_sqlite_to_supabase.py [path/to/database.db] [--with-users] [--replace]

* Reads SUPABASE_DB_URL from the environment / .env.
* Creates the Supabase schema if needed, keeps all row ids, and fixes the id sequences.
* app_users is NOT copied unless --with-users is given (old databases often still hold the
  public default passwords; without it the app creates admin/analyst from ADMIN_PASSWORD / ANALYST_PASSWORD).
* Refuses to write into non-empty tables unless --replace is given (which empties them first).
"""
import sqlite3
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import pgdb

# parents before children (foreign keys)
TABLES = [
    ("government_services", True), ("audit_logs", True), ("app_users", True),
    ("web_sources", True), ("web_pages", True), ("library_files", True), ("library_items", True),
    ("scan_items", True), ("chat_threads", False), ("chat_messages", True), ("shared_links", False),
]
FK = {"web_pages": ("source_id", "web_sources"), "library_items": ("file_id", "library_files"),
      "chat_messages": ("thread_id", "chat_threads")}
BATCH = 200


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    with_users, replace = "--with-users" in sys.argv, "--replace" in sys.argv
    path = args[0] if args else "database.db"
    if not pgdb.is_postgres():
        raise SystemExit("Set SUPABASE_DB_URL first (see .env.example).")
    src = sqlite3.connect(path)
    src_tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    pgdb.ensure_schema()
    pool = pgdb._get_pool()
    with pool.connection() as pg:
        existing = {}
        for t, _ in TABLES:
            existing[t] = pg.execute(f"SELECT count(*) FROM public.{t}").fetchone()[0]
        busy = [t for t, n in existing.items() if n and (t != "app_users" or with_users)]
        if busy and not replace:
            raise SystemExit(f"Supabase tables already contain data ({', '.join(busy)}). Use --replace to overwrite.")
        if replace:
            for t, _ in reversed(TABLES):
                if t == "app_users" and not with_users:
                    continue
                pg.execute(f"DELETE FROM public.{t}")
        for table, identity in TABLES:
            if table not in src_tables or (table == "app_users" and not with_users):
                print(f"- {table}: skipped")
                continue
            cols = [c[1] for c in src.execute(f'PRAGMA table_info("{table}")')]
            pg_cols = [r[0] for r in pg.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s", (table,))]
            cols = [c for c in cols if c in pg_cols]
            rows = src.execute(f'SELECT {",".join(chr(34)+c+chr(34) for c in cols)} FROM "{table}"').fetchall()
            if table in FK:   # skip orphans that would violate the new foreign keys
                fk_col, parent = FK[table]
                parent_key = "token" if parent == "shared_links" else "id"
                ok_ids = {r[0] for r in src.execute(f'SELECT {parent_key} FROM "{parent}"')}
                idx = cols.index(fk_col)
                kept = [r for r in rows if r[idx] in ok_ids]
                if len(kept) != len(rows):
                    print(f"  ! {table}: dropped {len(rows) - len(kept)} orphan rows")
                rows = kept
            ph = ",".join(["%s"] * len(cols))
            over = " OVERRIDING SYSTEM VALUE" if identity and "id" in cols else ""
            sql = f'INSERT INTO public.{table} ({",".join(chr(34)+c+chr(34) for c in cols)}){over} VALUES ({ph})'
            with pg.cursor() as cur:
                for i in range(0, len(rows), BATCH):
                    cur.executemany(sql, [tuple(pgdb._clean_param(v) for v in r) for r in rows[i:i + BATCH]])
            if identity and "id" in cols:
                pg.execute(
                    f"SELECT setval(pg_get_serial_sequence('public.{table}', 'id'), "
                    f"GREATEST((SELECT COALESCE(MAX(id), 0) FROM public.{table}), 1), "
                    f"(SELECT COUNT(*) > 0 FROM public.{table}))"
                )
            print(f"- {table}: {len(rows)} rows copied")
        pg.commit()
    print("Done. Start the app and check the Library, Websites and Chats tabs.")


if __name__ == "__main__":
    main()
