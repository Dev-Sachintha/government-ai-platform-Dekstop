GOVERNMENT AI PLATFORM — WINDOWS DESKTOP BUILD

1) Install Python 3.11 x64 and Microsoft Edge WebView2 Runtime.
2) Create a Supabase project and run supabase/001_platform_snapshots.sql.
3) Create a restricted PostgreSQL login role and configure .env from .env.example.
4) Run build_windows.bat on Windows.
5) Distribute the complete dist\GovernmentAIPlatform folder.

Read DESKTOP_CLOUD_MIGRATION.md before production use. Current cloud bridge stores
versioned SQLite snapshots in Supabase PostgreSQL and permits only one active writer.
A full normalized PostgreSQL + Supabase Auth migration is still required for concurrent
multi-user production use. Do not expose database owner credentials or service-role keys.
