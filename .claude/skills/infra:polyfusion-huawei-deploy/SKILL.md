---
name: polyfusion-huawei-deploy
description: |
  Sync the local PolyFusion repo to the huawei server (/home/huawei/PolyFusion) and
  operate its systemd service. Use when the user says "sync to huawei", "deploy
  to huawei", "restart polyfusion", "update polyfusion service", or when the
  huawei side of the project needs code, dependencies, or service state changes.

  Covers: (1) local→local-git-server→huawei sync chain, (2) huawei main reset
  from `local/main`, (3) Python deps installed to /home/huawei/.local (no venv,
  service runs as user `huawei`),
  (4) /etc/systemd/system/polyfusion.service, (5) the frps:8765 port conflict
  that forces PolyFusion to use port 8080.
allowed-tools:
  - Bash
  - Read
  - Edit
  - Write
  - Grep
  - Glob
author: PolyFusion ops
version: 1.0.0
---

# PolyFusion ↔ huawei deploy skill

Three pieces, in order. Each section ends with a "verify" step.

## 0. Topology — read this first

```
Local machine                                          huawei (Ubuntu 24.04, root)
─────────────                                          ──────────────────────────
/home/linden/code/work/PolyFusion  ──push──▶  /git-server/PolyFusion-local.git
       (work tree, main)            (cc6e38c…785d73f)        ▲
                                                               │ fetch + reset
                                                  /home/huawei/PolyFusion  (work tree, main)
                                                               │
                                                  systemd: polyfusion.service
                                                  User=huawei  (NOT root)
                                                  ExecStart=/usr/bin/python3 app/server.py
                                                  Port: 8765  ← see §4 (transient frp tunnels)
                                                  Deps: /home/huawei/.local/lib/python3.12/site-packages/
```

- **Local GitHub `origin` is read-only** for the local user `suyuexinghen` (403).
  Do not bother `git push origin` — it will fail. Use `local` instead.
- The "local" remote on the huawei side (`git://localhost:2222/...`) is a git
  daemon running on huawei itself that mounts the same `/git-server/...` repo.
  So one push from your machine lands on the huawei side in one fetch.
- `frps` (FRP server) holds ports 3000, 6000, 7000, 7500, 8001, 3306, 3389, 18765, 18789.
  Port 8765 is normally free, but a remote `frpc` client can claim it as a
  tunnel endpoint (that's what happened on 2026-07-01). If you see
  `OSError: [Errno 98]` on 8765, fall back to **8080**.

---

## 1. Sync code from local repo to huawei

```bash
# (on local) — commit any WIP first, then push
git status                       # must be clean
git add -A
git commit -m "..."              # only if there are staged changes
git push local main              # → /git-server/PolyFusion-local.git
```

```bash
# (on huawei) — fetch the new main and hard-reset
ssh huawei "cd /home/huawei/PolyFusion && \
  git fetch local && \
  git reset --hard local/main"
```

**Verify:**

```bash
ssh huawei "cd /home/huawei/PolyFusion && \
  git log --oneline -1 && \
  git rev-list --left-right --count local/main...HEAD"
# Expected:  HEAD = 785d73f or newer; count = "0\t0"
```

**Untracked files that must survive the reset** (they're not in any commit):

- `app/vendor/plotly-2.32.0.min.js` — bundled Plotly, used by `app/index.html`
  when offline. If a fresh huawei clone ever wipes this, copy it back from
  the local repo's untracked stash before restarting the service.

---

## 2. Install Python deps to /home/huawei/.local (no venv)

PolyFusion dependencies on huawei live in
`/home/huawei/.local/lib/python3.12/site-packages/`, not a venv and NOT
in `/root/.local/`. The service runs as user `huawei`, so the deps must
be installed as that user, not as root. Use `--user --break-system-packages`
(PEP 668 forces the latter on Ubuntu 24.04 system Python).

```bash
# Runtime deps from requirements.txt (run as huawei, so files land in his home)
ssh huawei "sudo -u huawei pip3 install --user --break-system-packages --timeout 180 \
  -r /home/huawei/PolyFusion/requirements.txt"

# Dev deps (only needed if you'll run pytest/ruff on huawei)
ssh huawei "sudo -u huawei pip3 install --user --break-system-packages --timeout 180 \
  pytest ruff matplotlib"
```

`matplotlib` is required by `polyfusion/tests/test_stellarator_nesting.py` —
forgetting it yields a collection error that fails the whole suite.

**Verify (must run as huawei, since deps live in his home):**

```bash
ssh huawei "sudo -u huawei python3 -c \
  'import supabase, jwt, netCDF4, h5py, numpy, matplotlib; print(\"deps OK\")'"
# Expected: deps OK
```

---

## 3. Run the test suite on huawei

```bash
ssh huawei "sudo -u huawei bash -lc 'cd /home/huawei/PolyFusion && \
  export PATH=/home/huawei/.local/bin:\$PATH && \
  ruff check . && \
  python3 -m pytest polyfusion/tests -q'"
# Expected: All checks passed! + 245 passed
```

If `ruff: command not found` → the export line was missing. The binary
lives in `/home/huawei/.local/bin/`, which is not on the default PATH.

---

## 4. PolyFusion systemd service

The unit file lives at `/etc/systemd/system/polyfusion.service`:

```ini
[Unit]
Description=PolyFusion 0-D fusion design web server
After=network.target

[Service]
Type=simple
User=huawei
Group=huawei
WorkingDirectory=/home/huawei/PolyFusion
ExecStart=/usr/bin/python3 /home/huawei/PolyFusion/app/server.py
Restart=on-failure
Environment=PORT=8765
Environment=PYTHONUSERBASE=/home/huawei/.local
Environment=SUPABASE_URL=https://tomvvnekqrtqwwgwfsft.supabase.co
Environment=SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

[Install]
WantedBy=multi-user.target
```

Apply or update the unit:

```bash
ssh huawei "sudo tee /etc/systemd/system/polyfusion.service >/dev/null <<'EOF'
[Unit]
Description=PolyFusion 0-D fusion design web server
After=network.target

[Service]
Type=simple
User=huawei
Group=huawei
WorkingDirectory=/home/huawei/PolyFusion
ExecStart=/usr/bin/python3 /home/huawei/PolyFusion/app/server.py
Restart=on-failure
Environment=PORT=8765
Environment=PYTHONUSERBASE=/home/huawei/.local
Environment=SUPABASE_URL=https://tomvvnekqrtqwwgwfsft.supabase.co
Environment=SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRvbXZ2bmVrcXJ0cXd3Z3dmc2Z0Iiwicm9sIjoiYW5vbiIsImlhdCI6MTc4Mjc3NTgwMCwiZXhwIjoyMDk4MzUxODAwfQ.b-KcBSa1y8LYNvTfBWvGiP_XvDRDkBOD3w_hV8nOyZc

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload"
```

Enable on boot + start now:

```bash
ssh huawei "sudo systemctl enable --now polyfusion"
```

**Verify (must check that the process is owned by huawei, not root):**

```bash
ssh huawei "sudo systemctl is-enabled polyfusion && \
  sudo systemctl is-active polyfusion && \
  ps -o pid,user,group -p \$(pgrep -f 'home/huawei/PolyFusion/app/server' | head -1) && \
  curl -s -o /dev/null -w 'http %{http_code}\n' http://localhost:8765/"
# Expected: enabled  active  huawei huawei  http 200
```

**Why `PYTHONUSERBASE` is in the unit file:** `python3` looks up user-site
packages via `site.getuserbase()`, which is `~` of the running user. As a
safety belt we set it explicitly so a future env change (e.g. `HOME=/tmp`)
can't make the interpreter fall back to the system site-packages.

### Port 8765 — default but can be claimed by a remote frpc tunnel

`frps` itself does NOT hold 8765. But any remote `frpc` client that asks
frps to expose port 8765 will temporarily bind it on the huawei side, and
the next PolyFusion restart will fail with `OSError: [Errno 98]`. If that
happens, either (a) wait for the frpc client to disconnect, or (b) move
PolyFusion to 8080 by editing `Environment=PORT=...` and `systemctl
daemon-reload && systemctl restart polyfusion`.

The user-facing public URL (whatever remote port frps forwards to) is
orthogonal to this — PolyFusion only binds to localhost.

### SUPABASE env vars

`app/server.py` and `polyfusion/auth.py` read `SUPABASE_URL` and
`SUPABASE_ANON_KEY` from `os.environ`. There is no `.env` autoload.
Inline them in the systemd unit as shown — the anon key is safe to embed
(it is also in the repo's `.env.example`).

---

## 5. Cleanup (only when the new service is stable)

Once the new service running as `huawei` on 8765/8080 has been verified
working for a full restart cycle:

```bash
ssh huawei "sudo systemctl stop polyfusion                  # safety
sudo rm -rf /root/PolyFusion                               # old root-owned deploy
sudo rm -rf /root/polyfusion-venv                          # old venv at /root
rm -rf /home/huawei/polyfusion-venv                        # huawei home venv
sudo rm -rf /root/.local                                   # old root-owned deps
sudo systemctl start polyfusion"
```

The cleanup is destructive — confirm with the user first.

---

## 6. Troubleshooting quick-reference

| symptom | cause | fix |
|---|---|---|
| `OSError: [Errno 98] Address already in use` | a remote frpc client tunneled 8765, or another service on 8080 | `sudo ss -tlnp \| grep <port>`; either wait for the frpc client to disconnect or move to `Environment=PORT=8080` |
| `ModuleNotFoundError: No module named 'jwt'` / `matplotlib` | deps not in user site, OR installed under wrong user | re-run §2 with `sudo -u huawei` so files land in `/home/huawei/.local/` |
| `Permission denied` pushing to `origin` | GitHub user lacks write | use `local` remote, not `origin` |
| `fatal: detected dubious ownership in repository` | git on huawei refuses unknown owner | `git config --global --add safe.directory /home/huawei/PolyFusion` |
| `ruff: command not found` | PATH missing `/home/huawei/.local/bin` | prefix with `export PATH=/home/huawei/.local/bin:$PATH` |
| `polyfusion.service: Scheduled restart job, restart counter is at N` | port in use → infinite restart loop | fix port, then `systemctl reset-failed polyfusion && systemctl start polyfusion` |
