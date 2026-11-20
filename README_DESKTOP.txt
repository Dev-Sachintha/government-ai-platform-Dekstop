GOVERNMENT AI PLATFORM - WINDOWS DESKTOP BUILD (Supabase cloud database)

1) Install Python 3.11 x64 and the Microsoft Edge WebView2 Runtime.
2) Create a Supabase project. Copy .env.example to .env and fill in SUPABASE_DB_URL,
   ADMIN_PASSWORD, ANALYST_PASSWORD and your AI key.
3) (Optional) import an existing database.db:  python migrate_sqlite_to_supabase.py database.db
4) Run build_windows.bat on Windows.
5) Distribute the complete dist\GovernmentAIPlatform folder (GovernmentAIPlatform.exe).

Read DESKTOP_CLOUD_MIGRATION.md first. Each desktop holds the database login in its .env:
use the restricted login role described there, never the Supabase owner/service-role key.
