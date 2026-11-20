# Desktop app + Supabase cloud database

## What changed
| Before | Now |
|---|---|
| One SQLite file (`database.db`), later a gzip snapshot of it in one Supabase row | Real PostgreSQL tables in Supabase, shared live by every user |
| Single writer at a time | Concurrent users, row-level writes, pooled connections |
| `cloud_database.py`, `persist.py` (GitHub/snapshot upload) | Removed. `pgdb.py` is the only database layer |
| Windows launcher | Unchanged (`desktop_launcher.py` + `build_windows.bat`) |

Code map: `pgdb.py` (connection pool, SQLite-to-PostgreSQL translation, restricted read-only SQL),
`pg_schema.py` / `supabase/schema.sql` (tables, indexes, row-level security, roles),
`migrate_sqlite_to_supabase.py` (one-time data import). The modules keep their small sqlite3-style calls;
`pgdb` translates `?` placeholders, case-insensitive `LIKE`, `COLLATE NOCASE`, `CURRENT_TIMESTAMP` and `lastrowid`.
If `SUPABASE_DB_URL` is empty the app still runs on local SQLite (development only).

## 1. Create the database
1. Supabase > New project. Save the database password.
2. Project Settings > Database > Connection string > **URI**. Use the *Session pooler* string if your network has no IPv6.
3. Put it in `.env` as `SUPABASE_DB_URL`, and set real `ADMIN_PASSWORD` / `ANALYST_PASSWORD`
   (the app refuses to create accounts with the public default or `CHANGE_THIS...` passwords).
4. Start the app once with the `postgres` connection: it creates all tables itself.
   (Or paste `supabase/schema.sql` into the Supabase SQL editor.)

## 2. Import old data (optional)
```
python migrate_sqlite_to_supabase.py path\to\database.db
```
Keeps row ids and fixes the id counters. Users are not copied unless you add `--with-users`
(old files may hold the public default passwords). Add `--replace` to overwrite non-empty tables.

## 3. Use a restricted login on desktops (recommended before distributing)
Every desktop copy has the database login in its `.env`. Do not hand out the owner login.
In the SQL editor (after step 1):
```sql
CREATE ROLE govai_app LOGIN PASSWORD 'a-long-random-password';
GRANT govai_app_rw, govai_chat_ro, govai_workbench_ro TO govai_app;
```
Then put `postgresql://govai_app:...@...` in the desktops' `.env` and add `GOVAI_SKIP_SCHEMA=1`.
Never ship the Supabase `service_role` key or the `postgres` password.
Even so, anyone with that `.env` can read every table, so treat it as a staff-only credential;
for broader audiences host one server instance and give users only its URL.

## 4. Build
`build_windows.bat` on Windows creates `dist\GovernmentAIPlatform\GovernmentAIPlatform.exe`.

## Security behaviour
* All tables have row-level security; Supabase's public API roles (`anon`, `authenticated`) see nothing.
* AI-written SQL (chat) and the admin Database Workbench run in a **read-only transaction**, with a 10 s timeout,
  5,000-row cap, and database roles that cannot see `app_users`, password hashes or file/photo bytes.
* `app_users` was previously visible to AI-written SQL; it is now blocked in code and by the role.
* Backup/restore: Supabase keeps its own backups (Dashboard > Database > Backups). The in-app button exports a CSV ZIP
  (without users); restoring from the app is disabled for the shared database.

## Not verified here
This was converted without access to a Supabase project or Windows. The SQL translation, SQLite fallback and driver
plumbing were tested; the PostgreSQL schema and live queries were not run. First run checklist:
sign in, add a website, add a library image and a PDF, create/rename/delete a chat, open the Workbench, create a user,
then open the app on a second computer and confirm it sees the same data.
Known follow-ups: Supabase Auth instead of the app's own user table; `pg_trgm` indexes if text search gets slow;
stored AI-SQL result tables are re-queried on every page rerun.
