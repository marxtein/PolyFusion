# A6 urllib + JWT + RLS Kill-Switch 实验报告

日期：2026-07-01；初次执行：2026-07-02
复核：2026-07-02（GREEN）
实验脚本：`scripts/kill_switch_rls_test.py`

## 实验目的

验证 `stdlib urllib + Authorization: Bearer <user_jwt> + apikey: <anon_key>` 访问 Supabase PostgREST 时，RLS 能按真实用户身份生效。这是 v1.2 P2/P3（用户历史、管理后台）数据访问层的前置 go/no-go 条件。

## 实验设计

1. 不创建临时表、不依赖 `exec_sql` 等危险 RPC。
2. 利用已存在的 RLS 保护表 `public.profiles`（schema.sql 中定义）进行隔离验证。
3. 用 service-role key 创建两个测试用户 A/B，并设置 username。
4. 用 stdlib `urllib` 调用 `/auth/v1/token?grant_type=password` 获取用户 access_token。
5. 用 stdlib `urllib` 调用 `/rest/v1/profiles?select=id,username,email`，分别带上 A/B 的 token。
6. 断言：
   - A 只能看到 A 的 profile；
   - B 只能看到 B 的 profile；
   - 匿名（仅 `apikey`）请求返回 401/403 **或** 200+空列表（两种 Supabase 默认行为都可接受）；
   - service-role key 可绕过 RLS（作为对照）。

## 执行环境

- Supabase 本地栈（`npx supabase start`）：`http://127.0.0.1:54321`，DB `127.0.0.1:54322`。
- schema 已应用：`supabase/schema.sql` v1.2（含 `is_admin()` SECURITY DEFINER 函数）。
- 远程项目（tomvvnekqrtqwwgwfsft）目前没有 `public.profiles` 表，schema 应用由用户在 Dashboard SQL Editor 执行（README A.6）。

## 初次执行（2026-07-02）发现的问题与修复

实验在第一次跑通时暴露了 **schema.sql 中的真实 bug**，正说明 kill-switch 是必要的：

### Bug 1：admin policy 自递归

原 v1.2 schema 中：

```sql
create policy "profiles_select_admin" on public.profiles
  for select to authenticated
  using (exists (select 1 from public.profiles p where p.id = auth.uid() and p.is_admin));
```

PostgREST 报 `42P17 infinite recursion detected in policy for relation "profiles"` —— 因为 policy 体里再查 `public.profiles` 会再次进入 RLS。

**修复**：新增 `public.is_admin(uid)` SECURITY DEFINER 函数，bypass RLS，policy 体只调用该函数。

```sql
create or replace function public.is_admin(uid uuid)
returns boolean language sql security definer set search_path = public stable as $$
  select exists (select 1 from public.profiles p where p.id = uid and p.is_admin);
$$;
```

### Bug 2：默认 GRANT 不足

本地 Supabase 默认不给 `authenticated`/`anon` 角色 SELECT 权限。PostgREST 报 `42501 permission denied for table profiles`。

**修复**：在 schema.sql 中显式 GRANT：

```sql
grant select on public.profiles to anon, authenticated, service_role;
grant select, insert, delete on public.computations to anon, authenticated, service_role;
```

### Bug 3：脚本对匿名响应判定过严

脚本原期待匿名请求必须 401/403。但 Supabase 的常见默认行为是：anon 角色能到达 PostgREST，但 RLS policy `to authenticated` 会把所有行过滤掉，返回 200 + `[]`。这也是安全的（无数据泄露）。

**修复**：脚本同时接受 `401/403` 与 `200 + 空列表`，仅当 `200` 且列表非空时才 FAIL。

## 最终执行结果

```
$ python scripts/kill_switch_rls_test.py
============================================================
Kill-switch experiment: urllib + user JWT + Supabase RLS
============================================================

[PREFLIGHT] Checking that public.profiles exists...
       public.profiles is present.

[1/5] Creating test users (with usernames)...
       user_a=7b6cdb37-370c-4cac-9be8-3c76e94f1de7
       user_b=6900f372-683e-41a1-8c22-68f2f1a04e47
[2/5] Logging in test users (stdlib urllib)...
       token_a and token_b obtained
[3/5] Querying profiles via stdlib urllib...
       user_a sees: {'ks_a_1653535a'}
       user_b sees: {'ks_b_1653535a'}
[4/5] Checking isolation...
       unauthenticated request returned 200 with empty list (anon RLS filter)
[5/5] Checking service-role key bypasses RLS...
       service-role sees 2 profile rows (expected: ≥2)

PASS: RLS isolation works with stdlib urllib + user JWT.
A6 path is GREEN. Proceed with v1.2 P2/P3 implementation.

[CLEANUP] Removing test users...
       done
```

## 结论

**A6 GREEN。** urllib + user JWT + apikey 头让 Supabase PostgREST 正确按用户身份执行 RLS：

- user_a token 只能查到 user_a 的 profile；
- user_b token 只能查到 user_b 的 profile；
- 匿名请求（仅 apikey）无任何行泄露；
- service-role key 可绕过 RLS（与设计一致，对照成立）。

v1.2 P2/P3 可基于此架构实施。

## 复现步骤

1. 启动本地 Supabase：`npx supabase init && npx supabase start`。
2. 应用 schema：`PGPASSWORD=postgres psql -h 127.0.0.1 -p 54322 -U postgres -d postgres -f supabase/schema.sql`。
3. 运行实验：
   ```bash
   SUPABASE_URL=http://127.0.0.1:54321 \
   SUPABASE_ANON_KEY=<local-anon-key-from-supabase-start-output> \
   SUPABASE_SERVICE_ROLE_KEY=<local-service-role-key-from-supabase-start-output> \
   python scripts/kill_switch_rls_test.py
   ```
4. 远程 Supabase 部署：把 `supabase/schema.sql` 在 Dashboard SQL Editor 中跑一次（README A.6），然后把 `.env.subabase` 的 URL/KEY 切到远程项目，再跑本脚本。

## 下一步

A6 GREEN → 进入 v1.2 P2a（`polyfusion/postgrest.py` urllib client）。
