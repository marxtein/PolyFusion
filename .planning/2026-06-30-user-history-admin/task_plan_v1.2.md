# PolyFusion 用户计算历史 + 管理后台 + 游客模式 — 实施方案 v1.2

> 起草：2026-06-30  
> 修订：2026-07-01（v1.2）  
> 关联反馈：杨明（用户量 / 使用单位 / 计算历史）、谢华生（游客试用）  
> 范围：在已上线的 Supabase auth 基础上，增加**用户维度的计算历史**、**管理后台只读统计**与**游客试用模式**，作为同一 milestone 交付。  
> v1.2 修订依据：`.planning/2026-06-30-user-history-admin/reviews/synthesis.md` 多 wrapper 评审结论。

---

## 1. v1.2 关键变更摘要

- **修复 A1-A7 全部阻塞问题**：表名 typo、admin policy、路由前缀、自封 admin 漏洞、FakeSupabase mock 预算、supabase-py 进 server.py、破坏性改动清单。
- **架构立场统一**：所有 admin 权限判定下沉到 SQL（RLS / 列级 GRANT），Python 端只透传 user JWT，不再自行判断角色。
- **A6 实施方式确定**：`app/server.py` 内用 stdlib `urllib` 直发 Supabase PostgREST，请求头带 `Authorization: Bearer <user_access_token>` + `apikey: <anon_key>`，让 RLS 按真实用户身份生效。
- **工时重估**：v1.1 原估 33-42h → v1.2 估 42-54h（含 A6 urllib client 4-6h、P3 重估、kill-switch 实验 3h）。
- **新增 kill-switch 实验**：v1.2 实施前必须先跑通“urllib + user JWT + RLS”最小验证；若失败需重新设计数据访问层。

---

## 2. 用户决策（v1.2 已拍板）

| # | 决策项 | v1.2 选择 | 理由 |
|---|---|---|---|
| D1 | 保存模型 | **混合保存**：显式“保存到历史”按钮 + 自动保留最近 10 次 | 防止“忘了点保存”，同时避免列表噪声；UI 区分“已保存”与“自动保存”。 |
| D2 | 历史 UI 形态 | **右侧抽屉（drawer）~320px** | 不遮挡中央 plot，便于对比历史条目与当前图。 |
| D3 | Affiliation 归一化 | **datalist 自动补全 + 写入时 normalize** | 预置常见单位（ASIPP/SWIP/清华/北大/MIT/PPPL…），入库时 lowercase/strip/别名映射，避免 group by 碎掉。 |
| D4 | 游客禁用“导出”范围 | **仅禁用 HTML 报告导出（`/api/report`）** | 参数 JSON 下载是用户自己输入的数据，不限制。 |
| D5 | 第一个 admin 邮箱 | **实施时替换占位符** | 迁移脚本最后一步前由用户提供；示例用 `admin@example.com`，禁止直接提交。 |
| D6 | P0/P1 顺序 | **P0 游客模式 与 P1 Schema 并行** | 文件不相交（server.py 路由 vs schema.sql），可并行 + `?flags=history` 灰度。 |

---

## 3. 数据模型（v1.2 修订）

### 3.1 新表 `public.computations`

```sql
create table if not exists public.computations (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  kind        text not null check (kind in ('run', 'scan')),
  config      text not null,
  preset      text,
  label       text,
  inputs      jsonb not null,
  summary     jsonb,
  created_at  timestamptz not null default now()
);

create index if not exists computations_user_created_idx
  on public.computations (user_id, created_at desc);
```

**v1.2 修正 A1**：索引表名从 `public.comcomputations` 改为 `public.computations`。

### 3.2 `profiles` 扩字段与列级权限（v1.2 修正 A4）

```sql
alter table public.profiles
  add column if not exists affiliation text,
  add column if not exists is_admin boolean not null default false;

-- 先收回 authenticated 对 profiles 的所有 update 权限
revoke update on public.profiles from authenticated;
-- 只开放 affiliation 列可写
grant update (affiliation) on public.profiles to authenticated;
```

**v1.2 修正 A4**：不再用 `profiles_update_own_affiliation` policy（它允许用户更新整行，可自封 admin）。改为列级 GRANT，SQL 层直接限制只能改 `affiliation`。

`is_admin` 仍只能由 SQL 直连手工翻转：

```sql
update public.profiles set is_admin = true where email = 'admin@example.com';
```

### 3.3 触发器更新

```sql
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
```

### 3.4 RLS（v1.2 修正 A2）

```sql
alter table public.computations enable row level security;

drop policy if exists "computations_select_own" on public.computations;
create policy "computations_select_own" on public.computations
  for select to authenticated using (auth.uid() = user_id);

drop policy if exists "computations_insert_own" on public.computations;
create policy "computations_insert_own" on public.computations
  for insert to authenticated with check (auth.uid() = user_id);

drop policy if exists "computations_delete_own" on public.computations;
create policy "computations_delete_own" on public.computations
  for delete to authenticated using (auth.uid() = user_id);

drop policy if exists "computations_select_admin" on public.computations;
create policy "computations_select_admin" on public.computations
  for select to authenticated using (
    exists (select 1 from public.profiles p where p.id = auth.uid() and p.is_admin)
  );

-- profiles：用户看自己，admin 看所有（v1.2 新增 A2）
drop policy if exists "profiles_select_admin" on public.profiles;
create policy "profiles_select_admin" on public.profiles
  for select to authenticated
  using (exists (select 1 from public.profiles p where p.id = auth.uid() and p.is_admin));
```

---

## 4. 后端 API（v1.2 修订）

### 4.1 架构立场：Python 不判 admin

- 所有权限判定下沉到 SQL RLS / 列级 GRANT。
- `app/server.py` 只负责：
  1. 从 cookie/header 取出用户 access_token；
  2. 本地验证 JWT 得到 `user_id`；
  3. 用 stdlib `urllib` 把请求转发到 Supabase PostgREST，带上 `Authorization: Bearer <access_token>` 和 `apikey: <anon_key>`；
  4. 把 PostgREST 响应原样或适度包装后返回。
- Python 端**不**调用 `supabase-py`，不查询 `profiles.is_admin`，不做二次角色判断。

### 4.2 urllib + PostgREST 客户端（v1.2 新增 A6）

新增轻量辅助模块（可放在 `polyfusion/postgrest.py` 或内嵌 `app/server.py`）：

```python
def _pg_rest(path: str, *, access_token: str, method="GET", query=None, body=None):
    """Forward one request to Supabase PostgREST with the user's JWT.

    Headers:
      Authorization: Bearer <user_access_token>
      apikey:        <SUPABASE_ANON_KEY>
      Prefer:        return=representation   (for mutating requests)
    """
    ...
```

关键原则：
- 用 user access_token，不是 service-role key；
- 用 anon_key 只做 `apikey` 头（Supabase 要求）；
- 这样 RLS 看到的 `auth.uid()` 就是真实用户，A/B 用户隔离、admin 判定全部在 Postgres 层成立。

### 4.3 路由分类（v1.2 修正 A3）

替换原来的 `PROTECTED_PATHS` 精确集合，改用前缀分类：

```python
# 游客可访问（GUEST_MODE=1 时）
GUEST_OK_PREFIXES = (
    "/api/run",
    "/api/scan",
    "/api/tokamak/parse_eqdsk",
    "/api/stellarator/equilibrium/preview",
)

# 始终需要登录
AUTH_REQUIRED_PREFIXES = (
    "/api/report",
    "/api/history",
    "/api/admin",
)

def _path_matches(path: str, prefixes):
    return any(path == p or path.startswith(p + "/") for p in prefixes)
```

**v1.2 修正 A3**：`/api/history/{id}`、`/api/admin/stats` 等子路由现在都会被拦截。

### 4.4 用户历史 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/history?limit=20&offset=0&kind=scan` | 列表，按 created_at 倒序 |
| GET | `/api/history/{id}` | 单条详情 |
| POST | `/api/history` | 保存 run/scan |
| DELETE | `/api/history/{id}` | 删除一条 |

实现：转发到 PostgREST `/rest/v1/computations`。RLS 自动过滤用户只能操作自己的行。

### 4.5 Admin API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/admin/stats` | 用户总量、近 7 天新增、top affiliations、计算总数 |
| GET | `/api/admin/users?limit=50&offset=0` | 用户列表 |

实现：同样转发到 PostgREST。RLS `computations_select_admin` / `profiles_select_admin` 保证非 admin 得到空集。Python 端把空集解释为空结果返回（不额外抛 403，避免泄露存在性）。

### 4.6 `/api/auth/me` schema（v1.2 修正 A7）

破坏性改动，显式列出：

```json
{
  "user_id": "uuid",
  "user": "username",
  "email": "user@example.com",
  "email_verified": true,
  "affiliation": "ASIPP",
  "is_admin": false
}
```

前端需同步读取 `is_admin` 控制 admin 入口显示。

---

## 5. 游客模式（v1.2 细化）

### 5.1 环境变量

```bash
GUEST_MODE=1       # 默认开；0 时恢复全严鉴权
REQUIRE_AUTH=1     # 保留本地调试后门（现有逻辑）
```

### 5.2 Principal 模型

```python
def _principal(self):
    user_id = self._authenticated_user_id()
    if user_id:
        return user_id, "user"
    if os.environ.get("GUEST_MODE", "1") == "1":
        return "__guest__", "guest"
    return None, None
```

### 5.3 速率限制（v1.2 细化）

```python
# 游客 compute：20/min/IP
# 已登录 compute：60/min/user_id
# auth mutation：10/min/IP（现状不变）
```

实现：统一 `_check_rate_limit(key, max, window=60)`，调用点显式传 key。

### 5.4 前端

- `/api/meta` 返回 `guest_mode` 字段；
- 未登录时显示 guest banner + “注册/登录”按钮；
- “保存到历史”“导出报告”按钮对游客 disabled + tooltip；
- 游客点击不直接弹 auth wall，而是 banner 提示“注册后解锁”。

**v1.2 修正 B4**：P0 阶段完全隐藏“保存到历史”按钮，P4 再显示并加游客禁用态。

---

## 6. 前端改动（v1.2 修订）

### 6.1 注册表单

```html
<div class="fld" id="authAffWrap" style="display:none">
  <label>单位 Affiliation <span>(可选)</span></label>
  <input id="authAff" list="affiliationOptions" ...>
  <datalist id="affiliationOptions">
    <option value="ASIPP">
    <option value="SWIP">
    <option value="清华大学">
    <option value="北京大学">
    <option value="MIT">
    <option value="PPPL">
  </datalist>
</div>
```

### 6.2 历史抽屉

右侧 ~320px drawer，列表项显示：
- 时间、位形、kind、预设/自定义
- 关键指标（run: Qfus/Pwall；scan: best Qfus）
- [载入] [删除]

“载入”把 `inputs` 灌回参数面板并自动重跑 `/api/scan`。

### 6.3 Admin Dashboard

独立 `admin.html` 或 `?view=admin` 模式，Plotly 展示：
- 总用户数 + 近 7 天新增
- Top 10 单位
- 计算总数（分 run/scan）

---

## 7. 分阶段实施（v1.2 重排）

| Phase | 内容 | 验收 | 工时 |
|---|---|---|---|
| **P0 游客模式** | 路由前缀分类、`_principal()`、分层 rate limit、前端 guest banner、隐藏保存按钮 | 游客可跑 POPCON；保存/导出禁用 | 7-9h |
| **P1 Schema** | `computations` 表、`profiles` 扩字段、列级 GRANT、RLS policy、触发器 | Dashboard 跑通，RLS 手工验证 | 3-4h |
| **P2a urllib PostgREST client** | 最小 `polyfusion/postgrest.py`，支持 GET/POST/DELETE + user JWT + apikey | kill-switch 实验通过 | 4-6h |
| **P2b History API** | `/api/history/*`、FakeSupabase `.table()` mock | pytest 全绿，curl CRUD 通 | 8-10h |
| **P3 Admin API** | `/api/admin/*`、依赖 P0 principal + P1 schema + P2a client | admin 拿到数据，普通用户空集 | 6-8h |
| **P4 前端 affiliation + 历史 drawer** | 注册表单、历史 drawer、载入逻辑 | 浏览器跑通保存→列表→载入 | 7-9h |
| **P5 Admin dashboard** | admin 页面、Plotly 指标 | admin 可见，普通用户无入口 | 4-5h |
| **Kill-switch 实验** | urllib+JWT+RLS 最小验证 | 实验报告 | 3h |

**总工时**：42-54h（约 1.5 周 full-time）。

---

## 8. Kill-Switch 实验计划（v1.2 新增，必须在 P2a 前完成）

### 8.1 目的

验证 `urllib + Authorization: Bearer <user_jwt> + apikey: <anon>` 访问 Supabase PostgREST 时，RLS 能按真实用户身份生效。若失败，整个 P2/P3 架构需重新设计。

### 8.2 实验步骤

1. 在 Supabase 创建测试表（或直接用本地 dev 项目）：
   ```sql
   create table public.test_rls (id serial primary key, user_id uuid references auth.users, note text);
   alter table public.test_rls enable row level security;
   create policy test_select_own on public.test_rls for select using (auth.uid() = user_id);
   ```

2. 注册测试用户 A、B，分别获取 access_token。

3. 用 Python stdlib `urllib` 发送：
   ```python
   req = urllib.request.Request(
       f"{SUPABASE_URL}/rest/v1/test_rls?select=*",
       headers={
           "Authorization": f"Bearer {token_a}",
           "apikey": ANON_KEY,
       }
   )
   ```

4. 断言：
   - A 的 token 只能看到 A 的行；
   - B 的 token 只能看到 B 的行；
   - 不带 token 返回 401 或空；
   - 带错误 token 返回 401。

### 8.3 判定

- **通过（绿色）**：进入 v1.2 实施。
- **失败（红色）**：停止 P2/P3，改用 service-role key + Python 权限判定（安全性降级但可行），或改用其他数据层方案。

---

## 9. 测试策略（v1.2 修订）

### 9.1 单元测试

- `test_postgrest_client.py`：urllib 客户端构造正确头、超时、错误处理。
- `test_history_api.py`：CRUD、跨用户隔离、配额超限。
- `test_admin_api.py`：admin 返回数据、普通用户空集、affiliation 聚合。
- `test_register.py`：affiliation 写入 profiles。
- `conftest.py`：FakeSupabase 扩展 `.table()` 链式 mock（select/insert/delete/eq/order/range/limit/single）。

### 9.2 集成测试

- 起 ThreadingHTTPServer，注册 → 登录 → run → POST /api/history → GET /api/history → DELETE → 404。
- 游客模式：无 cookie 时 `/api/run` 200，`/api/history` 401 `guest_blocked`，连续 21 次 scan 触发 429。
- RLS 真链路：A 写 → B 看必空 → B DELETE A 的 id 必 404（需对真 Supabase 跑）。

### 9.3 安全对抗测试

- 游客 rate-limit IP 隔离（X-Forwarded-For 链、IPv6-mapped IPv4 解析）。
- 尝试自封 admin（通过 update profiles set is_admin=true）必须被 SQL 层拒绝。

---

## 10. 风险与缓解（v1.2 更新）

| 风险 | 缓解 |
|---|---|
| A6 urllib+JWT 路径不成立 | kill-switch 实验前置；红色则改方案。 |
| FakeSupabase `.table()` mock 复杂 | P2b 第一子任务，工时 8-10h。 |
| 游客滥用算力 | 20/min/IP + CPU 监控 + 必要时收紧。 |
| affiliation 自由文本噪声 | datalist + normalize + 别名映射。 |
| admin 邮箱填错 | 迁移脚本最后一步前确认；fallback SQL 改。 |
| 老用户 affiliation 为空 | 不阻塞；admin top affiliations 初期可能不全，后续引导补填。 |

---

## 11. 破坏性改动清单（v1.2 新增 A7）

- `/api/auth/me` 响应新增 `user_id`、`affiliation`、`is_admin` 字段；旧前端忽略这些字段仍可运行，但看不到 admin 入口和单位信息。
- `app/server.py` 中 `_check_rate_limit` 签名从固定 auth mutation 改为 `(key, max, window=60)`；所有调用点同步更新。
- 移除 `PROTECTED_PATHS` 精确集合，改为 `GUEST_OK_PREFIXES` / `AUTH_REQUIRED_PREFIXES` 前缀匹配；新增 `/api/history`、`/api/admin` 受保护。
- `app/server.py` 不再依赖 `supabase-py` 进行 computations/profiles 数据访问；新增 `polyfusion/postgrest.py` urllib 客户端。

---

## 12. 修订记录

- **v1.0（2026-06-30）**：初稿。
- **v1.1（2026-06-30）**：追加游客模式。
- **v1.2（2026-07-01）**：应用 synthesis 评审 A1-A7 + B1-B10；统一 admin 判定下沉 SQL；改用 urllib+PostgREST；新增 kill-switch 实验；工时重估 42-54h。
