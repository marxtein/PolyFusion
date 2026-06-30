-- PolyFusion auth schema.
-- Run this in the Supabase Dashboard SQL Editor once per fresh project.
-- Idempotent: safe to re-run.

-- profiles mirrors auth.users with a PolyFusion-specific username column.
-- Username uniqueness is enforced here (not in app code) so concurrent sign-ups
-- cannot race; the AFTER INSERT trigger rolls back the auth.users insert if the
-- profiles insert fails (e.g. on unique violation).
create table if not exists public.profiles (
  id          uuid primary key references auth.users(id) on delete cascade,
  username    text unique not null
              check (char_length(username) between 3 and 32
                     and username ~ '^[a-zA-Z0-9_-]+$'),
  email       text not null,
  created_at  timestamptz not null default now()
);

alter table public.profiles enable row level security;

-- Users may read their own profile. No UPDATE policy is granted: profiles are
-- immutable from the client side; username changes require admin intervention.
drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own" on public.profiles
  for select to authenticated using (auth.uid() = id);

-- Auto-provision a profiles row when auth.users gains a row. The username is
-- pulled from raw_user_meta_data which the PolyFusion register flow sets via
-- supabase.auth.sign_up({options:{data:{username: ...}}}). SECURITY DEFINER
-- is needed because the inserting role (anon/authenticated) cannot otherwise
-- write to public.profiles.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, username, email)
  values (new.id, new.raw_user_meta_data->>'username', new.email);
  return new;
end; $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();
