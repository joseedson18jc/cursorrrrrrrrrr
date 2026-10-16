-- Warm-start snapshot store for services/snapshot.py.
-- Run once in a Supabase project (SQL editor or migration), after replacing
-- <SHA256_HEX_OF_SNAPSHOT_SECRET> with:  printf %s "$SNAPSHOT_SECRET" | sha256sum
--
-- Data lives in a schema PostgREST does not expose. The only API access is
-- two SECURITY DEFINER functions that verify the shared secret, so the
-- Supabase advisor warnings "RLS enabled, no policy" and "anon can execute
-- SECURITY DEFINER function" are expected by design.
create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

create table private.snapshots (
  id          text primary key,
  payload     text        not null,           -- base64(gzip(json))
  meta        jsonb       not null default '{}'::jsonb,
  updated_at  timestamptz not null default now()
);

create table private.settings (
  key   text primary key,
  value text not null
);

alter table private.snapshots enable row level security;
alter table private.settings  enable row level security;

insert into private.settings (key, value)
values ('snapshot_secret_sha256', '<SHA256_HEX_OF_SNAPSHOT_SECRET>');

create or replace function public.save_snapshot(secret text, snap_id text, payload text, meta jsonb default '{}'::jsonb)
returns timestamptz
language plpgsql
security definer
set search_path = ''
as $$
declare
  expected text;
  ts timestamptz := now();
begin
  select s.value into expected from private.settings s where s.key = 'snapshot_secret_sha256';
  if expected is null or encode(sha256(convert_to(coalesce(secret, ''), 'UTF8')), 'hex') <> expected then
    raise exception 'forbidden' using errcode = '42501';
  end if;
  if length(payload) > 20000000 then
    raise exception 'payload too large' using errcode = '54000';
  end if;
  insert into private.snapshots (id, payload, meta, updated_at)
  values (snap_id, payload, coalesce(meta, '{}'::jsonb), ts)
  on conflict (id) do update
    set payload = excluded.payload, meta = excluded.meta, updated_at = excluded.updated_at;
  return ts;
end;
$$;

create or replace function public.load_snapshot(secret text, snap_id text)
returns table (payload text, meta jsonb, updated_at timestamptz)
language plpgsql
security definer
set search_path = ''
as $$
declare
  expected text;
begin
  select s.value into expected from private.settings s where s.key = 'snapshot_secret_sha256';
  if expected is null or encode(sha256(convert_to(coalesce(secret, ''), 'UTF8')), 'hex') <> expected then
    raise exception 'forbidden' using errcode = '42501';
  end if;
  return query
    select sn.payload, sn.meta, sn.updated_at from private.snapshots sn where sn.id = snap_id;
end;
$$;

revoke all on function public.save_snapshot(text, text, text, jsonb) from public, anon, authenticated;
revoke all on function public.load_snapshot(text, text) from public, anon, authenticated;
grant execute on function public.save_snapshot(text, text, text, jsonb) to anon;
grant execute on function public.load_snapshot(text, text) to anon;
