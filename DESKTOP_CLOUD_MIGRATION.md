# Government AI Platform — Windows Desktop + Supabase

## What this package does
- Keeps the existing Streamlit feature set and opens it in a native Windows WebView window.
- Builds a Windows desktop distribution with PyInstaller (`build_windows.bat`).
- Adds a Supabase PostgreSQL persistence bridge. The current SQLite application database is compressed and stored in `public.platform_snapshots` as a versioned `BYTEA` snapshot.
- Restores the latest cloud snapshot when the desktop app starts and attempts an optimistic-revision save after application changes.

## Important current limitation
This is a **cloud-persistence compatibility stage**, not a completed normalized PostgreSQL migration. Existing modules directly issue SQLite SQL, so this package does not claim that every table is independently queried from Supabase. The snapshot bridge supports one active desktop writer at a time. If two desktop instances modify the same cloud database, revision conflict detection blocks the stale writer; it does not merge changes. Do not deploy this as a simultaneous multi-user database until the application tables and all SQL repositories have been migrated to native PostgreSQL and Supabase Auth/API authorization.

## 1. Create Supabase database
1. Create a Supabase project.
2. In SQL Editor, run `supabase/001_platform_snapshots.sql`.
3. Create a dedicated Postgres login role for the desktop application. Grant it only `SELECT, INSERT, UPDATE` on `public.platform_snapshots` (and schema usage). Do not use the Supabase `service_role` key or the database owner password in a distributed executable.
4. Copy the PostgreSQL URI from Project Settings → Database. Prefer the Supavisor session pooler URI if direct IPv6 connectivity is unavailable. Require SSL.

Example role setup (run as project database owner; replace password):
```sql
create role govai_client login password 'REPLACE_WITH_A_LONG_RANDOM_PASSWORD';
grant usage on schema public to govai_client;
grant select, insert, update on public.platform_snapshots to govai_client;
```

## 2. Configure desktop
1. Copy `.env.example` to `.env` (the build script creates a starter copy).
2. Set `SUPABASE_DB_URL` to the dedicated-role connection string.
3. Set strong unique `ADMIN_PASSWORD` and `ANALYST_PASSWORD` values before first launch.
4. Keep `.env` private. A database password distributed to end-user PCs can be extracted; for production deployments with untrusted clients, replace direct DB access with a hosted authenticated API and Supabase Auth.

## 3. Build on Windows
- Install Python 3.11 x64 and Microsoft Edge WebView2 Runtime.
- Open PowerShell/CMD in the project folder and run `build_windows.bat`.
- Output: `dist\GovernmentAIPlatform\desktop_launcher.exe` plus its support files.
- Distribute the whole `GovernmentAIPlatform` folder, not just the EXE. Keep `.env` protected and do not publish it.

A Windows EXE cannot be reliably cross-compiled on Linux/macOS with PyInstaller; run this script on Windows.

## 4. Existing services
The Android/PC monitoring FastAPI service remains separately deployable. Set `MOBILE_MONITOR_API_URL` and `MOBILE_MONITOR_API_KEY` in `.env` if it is used. Android MediaProjection and browser screen-sharing still require explicit user consent.

## 5. Production migration still required
For concurrent users and stronger security, migrate `app_users`, audit logs, chats, library metadata/files, scan catalogue, and web sources into normalized PostgreSQL tables; use Supabase Auth (or a hosted backend) for identity, enforce RLS/server-side authorization, move file bytes to a private Supabase Storage bucket, and replace the snapshot bridge with transactional repositories. Back up and test the existing `database.db` before cutover.
