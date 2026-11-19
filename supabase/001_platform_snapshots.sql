-- Government AI Platform desktop cloud-persistence compatibility table.
-- IMPORTANT: this is a versioned SQLite snapshot bridge, not the final normalized schema.
create table if not exists public.platform_snapshots (
    app_id text primary key,
    revision bigint not null default 0,
    db_gzip bytea not null,
    updated_at timestamptz not null default now(),
    updated_by text
);

-- Do not enable public/anon access. Desktop connects using a dedicated DB role.
revoke all on table public.platform_snapshots from anon, authenticated;
