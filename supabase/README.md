# Supabase Auth — setup, deployment, migration, and verification

This directory holds the Supabase-side artifacts for the PolyFusion email-auth
migration (plan: Option C — Supabase replaces the legacy scrypt+JSON auth
entirely). The web process talks to Supabase via the anon key only; the
service-role key is loaded **exclusively** by the one-shot migration script.

| File | Purpose |
|------|---------|
| `schema.sql` | `public.profiles` table + RLS policies + auth triggers. Run once per fresh project and re-run after schema updates. |
| `README.md` | This document — setup, local dev, Huawei deploy runbook, migration workflow, manual verification checklist. |

Companion files outside this directory:

- `scripts/migrate_users_to_supabase.py` — idempotent legacy-user migration.
- `scripts/migrate_computations_to_local_history.py` — optional one-shot export from legacy Supabase `public.computations` to local SQLite history.
- `polyfusion/auth.py` — anon-key Supabase adapter (JWT verify, register,
  login, logout, resend, validate_session).
- `app/server.py` — HTTP routes + cookies + CSRF + rate limit.
- `polyfusion/history.py` — local SQLite storage for run/scan history.
- `polyfusion/report_cache.py` — local SQLite storage for full-report cache.
- `.env.example` — env template (URL + ANON only; service role never lives here).

---

## A. Supabase project setup

1. **Create the project** at [supabase.com](https://supabase.com). The
   **Singapore** region (`ap-southeast-1`) gives the best latency to the
   Huawei deployment and to mainland-China users.
2. **Record three values** from *Project Settings → API*:
   - `SUPABASE_URL` (`https://<project>.supabase.co`)
   - `SUPABASE_ANON_KEY` — public, loaded by the web process.
   - `SUPABASE_SERVICE_ROLE_KEY` — privileged, loaded **only** by the
     migration script. Treat it like a database root password.
3. **Auth → Providers → Email**: enable Email/Password. Toggle **Confirm
   email**:
   - **Production**: ON (users must click the verification link before login
     works).
   - **Local dev**: OFF (skip the email round-trip while iterating).
4. **Auth → URL Configuration**:
   - **Site URL** = `http://121.36.110.12:8765` (Huawei production origin).
   - **Redirect URLs** allow-list: add the production origin **and**
     `http://127.0.0.1:8765` / `http://localhost:8765` for local dev.
5. **Auth → Email Templates** — customise **Confirm signup** and **Reset
   Password** to mention PolyFusion by name. This is an anti-phishing measure:
   the legacy migration sends a "Reset Password" email out of the blue, so the
   template must clearly identify itself as a PolyFusion system email. Leave
   `{{ .ConfirmationURL }}` / `{{ .Token }}` placeholders intact — Supabase
   injects the real link.
6. **SQL Editor** → open `supabase/schema.sql` from this repo → **Run**. The
   script is idempotent; re-running is safe.
7. **Free-tier email limit**: Supabase's built-in SMTP caps at **~3 auth
   emails/hour**. For the legacy migration this means batching — see
   [section D](#d-migration-workflow). For normal operation (single sign-ups)
   it is rarely hit.

---

## B. Local dev setup

1. `cp .env.example .env` and fill in `SUPABASE_URL` + `SUPABASE_ANON_KEY`.
2. `pip install -r requirements.txt` (pulls `supabase`, `pyjwt`,
   `cryptography`).
3. `python app/server.py`. Open <http://127.0.0.1:8765>.
4. **Register** a test user → check your inbox → click the verification link →
   log in. If you set *Confirm email* OFF for dev, registration logs you in
   immediately.
5. Sanity check: `GET /api/auth/me` against the running server should return
   your username/email with `email_verified=true` once you are logged in.

Run/scan history and full-report cache are stored locally by the web process in
SQLite. By default they use `~/.polyfusion/history.sqlite3` and
`~/.polyfusion/report_cache.sqlite3`; override with `POLYFUSION_HISTORY_DB` and
`POLYFUSION_REPORT_CACHE_DB` if the deployment service user needs explicit
writable paths. These local stores do not require Supabase tables or RLS policies.

If existing Supabase computation history should be preserved, run the one-shot
migration before switching production traffic:

```
SUPABASE_SERVICE_ROLE_KEY=... \
  python scripts/migrate_computations_to_local_history.py \
  --db ~/.polyfusion/history.sqlite3
```

If history is not important, skip the migration and PolyFusion will start from an
empty local history database.

`requirements.txt` and the dev toolchain (`pytest`, `ruff`) are expected to be
installed in the active environment.

---

## C. Huawei deployment runbook

Follow these steps in order. The three checkpoints (A/B/C) are mandatory
go/no-go gates — do not proceed past a failed checkpoint.

**Pre-flight (local):**
1. Supabase project is created and the three keys (URL / ANON / SERVICE) are
   recorded.
2. `supabase/schema.sql` has been run successfully in the Supabase SQL Editor.
   **Checkpoint A — database ready.** Verify by running
   `select count(*) from public.profiles;` (should return `0`, not an error).

**Deploy:**
3. `git tag pre-supabase-migration` — rollback anchor. Push the tag.
4. On the Huawei host: `cp /root/polyfusion.env /root/polyfusion.env.bak`.
5. Write `/root/polyfusion.env` (chmod 600) containing **only**:
   ```
   SUPABASE_URL=https://<project>.supabase.co
   SUPABASE_ANON_KEY=eyJhbGc...
   PORT=8765
   REQUIRE_AUTH=1
   ```
   **Never** put `SUPABASE_SERVICE_ROLE_KEY` in this file — systemd
   EnvironmentFile is readable by the service user and persists across reboots.
6. Edit `/etc/systemd/system/polyfusion.service` to use
   `EnvironmentFile=/root/polyfusion.env`.
7. `cd /root/PolyFusion && git fetch local && git merge local/main`.
8. `/root/polyfusion-venv/bin/pip install -r requirements.txt`.
9. `systemctl daemon-reload && systemctl restart polyfusion`.
10. `curl -s http://121.36.110.12:8765/api/meta | head -c 200` returns 200;
    `curl -s http://121.36.110.12:8765/api/auth/me` returns
    `{"user":"__anon__","email":null,"email_verified":false}`.
    **Checkpoint B — new code is live.**

**Migrate:**
11. In a one-shot shell (NOT systemd), with the service-role key in env:
    ```
    SUPABASE_SERVICE_ROLE_KEY=... \
      /root/polyfusion-venv/bin/python \
      scripts/migrate_users_to_supabase.py
    ```
12. From a browser, walk a full register → inbox → click link → login flow.
    **Checkpoint C — user can register.** If this fails, roll back.

**Rollback** (if any checkpoint fails):
```
cd /root/PolyFusion
git checkout pre-supabase-migration
cp /root/polyfusion.env.bak /root/polyfusion.env
systemctl restart polyfusion
```
The legacy `users.json` / `sessions.json` are NOT deleted by the migration —
they are merely archived (see section D), so rolling back restores the
pre-migration auth surface fully.

---

## D. Migration workflow

The migration moves legacy `~/.polyfusion/users.json` users into Supabase
Auth. Each legacy user receives a "Reset Password" email; their old scrypt
hash is discarded (Supabase never sees it) and they pick a fresh password via
the recovery link.

> **Supabase internal SMTP caveat.** The Supabase admin API can only send
> *account-related* emails (invite, recovery, magic link). It has **no**
> general-purpose notification sender. The T-2 day pre-announcement therefore
> goes out via a one-shot external SMTP (Resend, Mailgun free tier, or a
> project-owned SMTP). For very small user sets (≤5), a manual IM/email heads-up
> is sufficient.

**T-2 day — pre-announce** (external SMTP):
- Collect every email from `users.json`.
- Send: *"PolyFusion will switch its login system on T day. You will receive a
  'Reset Password' email from PolyFusion that day — it is legitimate. Click the
  link inside to choose your new password."*

**T day — migrate**:
1. Back up the legacy store: `cp ~/.polyfusion/users.json ~/.polyfusion/users.json.archived`
   (do this on the Huawei host where the file actually lives).
2. Run the migration script (see step 11 of the runbook). The script:
   - Reads `users.json`.
   - For each entry with a non-null email:
     - `admin.create_user({email, password: <random 32 bytes>, email_confirm: True})`
       — creates the `auth.users` row with a throwaway password and marks the
       email verified, so Supabase does **not** send a confirmation email here.
     - `admin.generate_link({type: "recovery", email})` — Supabase sends the
       project's **Reset Password** template, which is the email the user
       actually acts on.
   - Records `{email, user_id, migrated_at}` in `migration_state.json`.
   - **Idempotent**: re-running skips every email already in the state file.
   - **Already-registered**: recorded as `skipped_existing`, not treated as a
     failure.
   - **Network errors**: retried 3× with exponential backoff (1s, 2s, 4s);
     if still failing, logged to the state file as `errors` and the run
     continues (exit code 2 = partial failure).
   - **Free-tier rate limit**: prints a warning if the user count exceeds the
     batch threshold (default 3), then sleeps `--batch-sleep` seconds (default
     1800) after every `--batch-size` users. Pass `--batch-size 0` to disable
     batching (e.g. on a Pro plan).

**T+1 day — archive**:
- `mv ~/.polyfusion/users.json.archived ~/.polyfusion/users.json.archived.final`
  (or move off-host to cold storage). The legacy login entry point is now
  closed.

Exit codes: `0` = clean (or fully idempotent re-run), `2` = partial failure
(see `migration_state.json["errors"]` and the log).

---

## E. Manual verification checklist

Run this against a local dev server (or the Huawei staging instance) after a
fresh deploy. It is intentionally manual — these are end-to-end checks the
pytest suite cannot perform because they involve real email delivery and real
browser cookie behavior.

- [ ] Local env loads: `python app/server.py` boots with no auth errors.
- [ ] **Register** a fresh email → a confirmation email arrives in the inbox →
  click the verification link → log in with the same email + password.
- [ ] `GET /api/auth/me` while logged in returns
  `{"user": "...", "email": "...", "email_verified": true}`.
- [ ] **Logout**: both cookies (`polyfusion_session` and `polyfusion_refresh`)
  are cleared from the browser. A subsequent `/api/auth/me` returns the anon
  shape.
- [ ] **Rate limit**: 11 rapid `/api/auth/register` attempts from the same IP
  → the 11th returns HTTP 429.
- [ ] **CSRF**: a cross-origin POST to `/api/auth/login` (Origin header set
  to a disallowed host) returns HTTP 403.
- [ ] **JWT auto-refresh**: log in, then fast-forward the access token to
  within 5 minutes of expiry (e.g. by waiting, or by minting a near-expiry
  token in a dev build). The next `/api/auth/me` should transparently refresh
  the session and return a fresh `polyfusion_session` cookie, without forcing
  a re-login.

If all of the above pass, the migration is complete and the auth surface is
production-ready.
