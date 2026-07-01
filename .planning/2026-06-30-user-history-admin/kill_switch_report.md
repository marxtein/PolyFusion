# A6 urllib + JWT + RLS Kill-Switch 实验报告

日期：2026-07-01
实验脚本：`scripts/kill_switch_rls_test.py`

## 实验目的

验证 `stdlib urllib + Authorization: Bearer <user_jwt> + apikey: <anon_key>` 访问 Supabase PostgREST 时，RLS 能按真实用户身份生效。这是 v1.2 P2/P3（用户历史、管理后台）数据访问层的前置 go/no-go 条件。

## 实验设计

1. 不创建临时表、不依赖 `exec_sql` 等危险 RPC。
2. 利用已存在的 RLS 保护表 `public.profiles`（schema.sql 中定义）进行隔离验证。
3. 用 service-role key 创建两个测试用户 A/B，并设置 username。
4. 用 stdlib `urllib` 调用 `/auth/v1/token?grant_type=password` 获取用户 access_token。
5. 用 stdlib `urllib` 调用 `/rest/v1/profiles?select=id,username,email`，分别带上 A/B 的 token。
6. 断言：A 只能看到 A 的 profile；B 只能看到 B 的 profile；匿名请求被拒绝；service-role key 可绕过 RLS（作为对照）。

## 执行结果

```text
$ python scripts/kill_switch_rls_test.py
============================================================
Kill-switch experiment: urllib + user JWT + Supabase RLS
============================================================

[PREFLIGHT] Checking that public.profiles exists...
FATAL: public.profiles is missing from the Supabase project.
       Apply supabase/schema.sql in the Supabase Dashboard SQL Editor,
       then re-run this experiment.
```

## 结论

**当前状态：实验无法完成，因为目标 Supabase 项目尚未应用 `supabase/schema.sql`。**

这不是 urllib+JWT+RLS 架构本身失败，而是 schema 未部署。`public.profiles` 表不存在，导致 PostgREST 返回 `PGRST205`（表不在 schema cache 中）。

## 阻塞项

- 必须先在 Supabase Dashboard SQL Editor 中执行 `supabase/schema.sql`（已更新为 v1.2 完整版，包含 `profiles` 扩字段、`computations` 表、RLS policy、列级 GRANT）。
- schema 应用后，重新运行 `python scripts/kill_switch_rls_test.py` 即可得到 GREEN/RED 判定。

## 下一步

1. 在 Supabase Dashboard 运行 `supabase/schema.sql`。
2. 重新跑 kill-switch 实验。
3. 若 GREEN：进入 P2a（`polyfusion/postgrest.py` urllib client）。
4. 若 RED：停止 P2/P3，重新设计数据访问层。
