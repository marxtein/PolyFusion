-- PolyFusion v1.2 schema.
-- Run this in the Supabase Dashboard SQL Editor once per fresh project.
-- Idempotent: safe to re-run.

-- profiles mirrors auth.users with PolyFusion-specific columns.
-- Username uniqueness is enforced here (not in app code) so concurrent sign-ups
-- cannot race; the AFTER INSERT trigger rolls back the auth.users insert if the
-- profiles insert fails (e.g. on unique violation).
create table if not exists public.profiles (
  id          uuid primary key references auth.users(id) on delete cascade,
  username    text unique not null
              check (char_length(username) between 3 and 32
                     and username ~ '^[a-zA-Z0-9_-]+$'),
  email       text not null,
  affiliation text,
  is_admin    boolean not null default false,
  created_at  timestamptz not null default now()
);

alter table public.profiles enable row level security;

-- Users may read their own profile.
drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own" on public.profiles
  for select to authenticated using (auth.uid() = id);

-- SECURITY DEFINER helper that checks admin status without triggering infinite
-- recursion in RLS policies. Inline subqueries on public.profiles inside a
-- policy ON public.profiles recurse; this function bypasses RLS via the
-- security definer escape hatch, so the policy body never re-enters RLS.
create or replace function public.is_admin(uid uuid)
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select exists (select 1 from public.profiles p where p.id = uid and p.is_admin);
$$;

grant execute on function public.is_admin(uuid) to authenticated, anon, service_role;

-- Current-user account deletion. Runs with definer privileges so the caller can
-- delete their own auth.users row without exposing the service-role key to the
-- web process; profiles cascade via their foreign key.
create or replace function public.delete_current_user()
returns boolean
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  target_uid uuid := auth.uid();
begin
  if target_uid is null then
    raise exception 'not authenticated' using errcode = '28000';
  end if;

  delete from auth.users where id = target_uid;
  return found;
end;
$$;

revoke all on function public.delete_current_user() from public;
grant execute on function public.delete_current_user() to authenticated;

-- Admins may read all profiles (for the admin dashboard).
drop policy if exists "profiles_select_admin" on public.profiles;
create policy "profiles_select_admin" on public.profiles
  for select to authenticated using (public.is_admin(auth.uid()));

-- Column-level GRANT: users can only update their own affiliation.
-- Revoke any broader update permission first, then grant just the one column.
revoke update on public.profiles from authenticated;
grant update (affiliation) on public.profiles to authenticated;

-- Explicit table privileges for the anon/authenticated/service_role roles.
-- PostgREST never runs queries as `postgres`; every role that will appear in a
-- Bearer token MUST have GRANTs on the tables it touches.
grant select on public.profiles to anon, authenticated, service_role;

-- Auto-provision a profiles row when auth.users gains a row. The username and
-- affiliation are pulled from raw_user_meta_data which the PolyFusion register
-- flow sets via supabase.auth.sign_up({options:{data:{username: ..., affiliation: ...}}}).
-- SECURITY DEFINER is needed because the inserting role (anon/authenticated)
-- cannot otherwise write to public.profiles.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, username, email, affiliation)
  values (
    new.id,
    new.raw_user_meta_data->>'username',
    new.email,
    new.raw_user_meta_data->>'affiliation'
  );
  return new;
end; $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();
