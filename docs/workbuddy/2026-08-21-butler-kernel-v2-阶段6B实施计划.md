# Butler Kernel v2 阶段 6B Implementation Plan：管理配置前端与搜索来源/降级体验

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:test-driven-development` while implementing each task, and use `superpowers:verification-before-completion` before any completion claim. Do not start implementation until the user approves this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不切流 Butler Kernel v2、不改变旧 chat 执行语义的前提下，交付安全可用的管理员配置前端、请求级联网授权闭环，以及向后兼容的来源/降级展示能力。

**Architecture:** 后端继续复用阶段 5/6A 的 `system_configs → effective config`、Butler Policy/Executor 和统一 API；6B 只补动态 feature capability、`user_opt_in` 最终闸门、管理员只读 KB 契约和 citation 可选字段兼容。前端新增独立 AdminLayout 与六页控制面，所有敏感字段使用“脱敏展示与新值输入分离”的 SecretField；聊天侧只消费 citation/degraded 事件，不在 6B 建立旧 chat 到 web search 的在线执行链。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy async、pytest、Vue 3、Pinia、Vue Router、Vitest、Vue Test Utils、Playwright、Vite。

**Spec:** `docs/superpowers/specs/2026-08-18-butler-kernel-v2-design.md`；上位总计划 `docs/superpowers/plans/2026-08-18-butler-kernel-v2.md` Task 9–11；阶段前置 `docs/workbuddy/2026-08-20-butler-kernel-v2-阶段6实施计划.md`。

## Global Constraints

- 后端仓库 `D:\math-arena`，当前基线 branch `feat/backend-m1`、HEAD `6dc58f00eb8abd56d974671126723cebd50b551e`。
- 前端独立仓库 `D:\frontend`，当前基线 branch `master`、HEAD `f1b2646172d5c4fed5142a8337f4dab9f2c79375`。
- 两仓库均有未提交用户资产。禁止 reset、checkout、clean、stash、覆盖或提交无关改动；实施时只暂存本计划 File Map 中的 6B 文件。
- 不触碰主仓库旧 `apps/web` 删除项，不修改 M3 teacher 文件，不解决 M3 测试债务。
- 不修改数据库模型或 Alembic；继续使用既有 `system_configs` 和加密工具。
- 不切流 v2；`BUTLER_V2_ENABLED=false`、`BUTLER_V2_SHADOW=false` 默认值不变，`_v2_migrated_scenes()` 保持空集合。
- 不新增在线 `run_v2_chat`，不让旧 chat 调用 `xingchen.web_search`，不宣称真实联网搜索已在学生对话生效。
- F14、`wf_verify_derivation`、`lean.*`、论文评审、多智能体均不进入 6B。
- 搜索默认关闭；远程搜索必须同时满足：本地真实拒答、服务端 `web_search_enabled=true`、本次请求 `web_search_opt_in=true`、Policy/Executor 允许。
- 管理配置 GET 不得返回原始密钥；空白密钥输入表示“保持当前”，只有显式清除动作才发送 `null`。
- 来源 URL 只允许 `http:`/`https:`；无效协议只显示文本，不得成为可点击链接。

---

## 1. 范围审计结论

### 1.1 6B 正式范围

| 子范围 | 交付物 | 范围依据 |
|---|---|---|
| 管理员控制面 | `/admin/overview`、`model`、`xingchen`、`cloud-kb`、`kb-bench`、`butler` 六页，独立布局、导航、角色守卫、可发现入口 | Butler 总计划 Task 11 明确要求可用 `/admin/*`、保存/测试、角色守卫 |
| Butler 授权 | GET/PUT `/api/admin/system/butler` 前端接入；`web_search_enabled`、`external_allowed` 可查看、保存、恢复默认 | 阶段 5 已有后端控制面，6B 补 UI |
| Feature 联动 | `/api/agent/features.capabilities.web_search_opt_in_enabled` 读取有效 Butler 配置，前端严格布尔 fail-closed | 阶段 6A 传输链的显示门控闭环 |
| 最终联网闸门 | `_h_web_search` 同时检查 `global_enabled` 和 `user_opt_in`；本地检索仍优先 | Policy/Executor 请求级授权不可被 handler 绕过 |
| 管理 KB 试验台 | admin 可明确访问 docs/chunks/retrieve/eval 的只读路径；import 仍仅 teacher/researcher | `/admin/kb-bench` 的最小后端依赖 |
| 来源展示 | citation 可选字段 `title/url/snippet/retrieved_at` 可透传、重放和渲染；旧 citation 回退 `source/loc/chunk_id` | 总计划 Task 9 的规范来源 + Task 11 的来源显示 |
| 降级展示 | 前端可消费 `degraded` SSE 或历史 block，并显示非阻塞解释 | Task 11 的“失败保留本地答案并显示降级” |
| 验证 | 后端聚焦/全量、前端 Vitest/typecheck/build/Playwright、权限与密钥回归 | 不以静态页面存在代替可用性 |

### 1.2 明确不属于 6B

- 旧 `/api/agent/chat` 切换到 Butler Kernel v2。
- 让旧 chat 在线调用 `xingchen.web_search`，或把 `_h_web_search().data.sources` 映射进旧 `qa_rag` citation。
- 为旧 chat 新增 `degraded` SSE 生产逻辑。当前旧链路只发 citation/badge；6B 交付的是消费与展示能力。
- 星辰 YAML、flow registry 名称、数据库/Alembic、M3 教师端、M4/F14 科研端改造。
- 重做学生/教师布局、全局设计系统或与 admin 无关的 API。

### 1.3 原计划决策已冻结

- **6B4 citation 扩展：纳入。** 只增加可选字段、信封重放和前端渲染；真实 web search 来源映射留待 v2 场景切流。
- **6B5 测试按钮：纳入。** model、cloud-kb、embedding、workflow 的既有 `/test` 端点必须在 UI 暴露并有状态展示。
- **Admin 页面范围：六页。** 五个既有 `adminNav` 页面加 Butler 授权页；这是总计划 Task 11，不裁成单页。

## 2. 当前候选实现审计（2026-08-21）

当前工作区已经存在未提交 6B 候选代码。它们是待审用户资产，执行计划时在原位修正，不得删除后重做。

| 项目 | 当前证据 | 状态 |
|---|---|---|
| features 读取有效配置 | `agent_router.py` 已调用 `resolve_butler_authorization` | Candidate complete，需保留回归测试 |
| handler 检查 user opt-in | `workflow_tools.py` 已检查 `auth.user_opt_in` | Candidate complete，需保留并发/无授权测试 |
| admin KB docs/chunks/eval | 已显式加入 admin；retrieve 依赖管理员账号偶然同时拥有 student role | Partial；必须把 admin 写入 retrieve 契约，并用 admin-only JWT 测试 |
| 六页 admin + layout/nav/guard | 文件和路由均存在 | Partial；管理员根路径仍去 `/overview`，缺可发现入口与路由测试 |
| model/xingchen/embedding 密钥 | GET 脱敏值被放进 `v-model`，保存时原样 PUT | **Blocking**；会把掩码字符串加密成新密钥 |
| cloud-kb 动态凭证 | 已有凭证行加载为空，但保存把空值转为 `null` | **Blocking**；会清除所有未编辑的已存凭证 |
| 工作流配置 | 页面只切换 enabled、执行 test；flow_id/timeout 只读 | Partial；不满足“配置前端” |
| 来源卡片 | 安全的 `window.open` 已有，但展开区 anchor 未复用安全 URL | Partial；javascript 等协议不得成为链接 |
| degraded/citation 模型测试 | `test/messageModel.test.ts` 5 项通过 | Partial；无 SourceCard、MessageBubble、admin route/secret/page 测试 |
| 在线降级链 | 旧 agent chat 没有 `degraded` SSE producer | Out-of-scope；不得宣称已在线闭环 |

### 2.1 已执行的只读验证

- 后端 `tests/test_iter05_kb.py -k TestKbAdminAccess`：2 passed；但 retrieve 成功依赖管理员登录同时带 student role，尚未证明 admin-only token。
- 前端 `npm run test:run`：10 files / 54 tests passed；无 admin 页面、SecretField 或 SourceCard 组件测试。
- 前端 `npm run typecheck`：退出码 0。
- 两仓库 `git diff --check`：无 whitespace error，仅现有 LF→CRLF 警告。
- 上述通过不能覆盖密钥误写、管理员入口和工作流编辑缺口，因此当前候选实现 **No-Go for commit/completion**。

## 3. File Map

### Backend

- Modify `services/api/app/butler/workflow_tools.py`：请求级 opt-in 最终闸门；不改变 local-first。
- Modify `services/api/app/gateway/agent_router.py`：features 读取 Butler 有效配置。
- Modify `services/api/app/gateway/kb_router.py`：admin 只读 KB bench 权限显式化。
- Test `services/api/tests/test_admin.py`：features 与 Butler 配置联动。
- Test `services/api/tests/test_butler_workflow_tools.py`：global/user/local 三条件矩阵。
- Test `services/api/tests/test_iter05_kb.py`：admin-only KB bench 权限。
- Test `services/api/tests/test_m1_fixes.py`：citation 可选字段信封重放。

### Frontend

- Create/modify `src/layouts/AdminLayout.vue`、`src/components/admin/AdminNav.vue`。
- Create `src/components/admin/SecretField.vue`、`src/components/admin/HealthBadge.vue`。
- Create/modify `src/components/common/Toggle.vue`。
- Create/modify six files under `src/pages/admin/`。
- Create/modify `src/components/chat/SourceCard.vue`。
- Modify `src/App.vue`、`src/api/index.js`、`src/config/nav.js`、`src/router/index.js`。
- Modify `src/components/chat/MessageBubble.vue`、`src/components/chat/messageModel.js`。
- Create `test/admin/router.test.ts`、`test/admin/secretField.test.ts`、`test/admin/pages.test.ts`、`test/sourceCard.test.ts`。
- Modify `test/messageModel.test.ts`。
- Create `e2e/phase6b-admin.spec.ts`。

## 4. Implementation Tasks

### Task 1: 锁定双仓库基线与候选 diff

**Files:** Read only; update only execution evidence in this plan.

**Produces:** 可审计的 6B 文件白名单，避免混入 M3/M2 并行资产。

- [ ] 记录 branch、HEAD、status：

```powershell
git -C D:\math-arena branch --show-current
git -C D:\math-arena rev-parse HEAD
git -C D:\math-arena status --short
git -C D:\frontend branch --show-current
git -C D:\frontend rev-parse HEAD
git -C D:\frontend status --short
```

- [ ] 只检查 File Map 范围 diff。若 HEAD 变化，重新审计，不 reset。
- [ ] 断言 diff 不含 teacher domain、Alembic、`apps/web`、CI/deploy 或 F14 文件。

### Task 2: 后端 features 与 web search 最终授权闸门

**Files:** `agent_router.py`、`workflow_tools.py`、`test_admin.py`、`test_butler_workflow_tools.py`。

**Consumes:** `resolve_butler_authorization(db)`；`ToolExecutionContext.web_search_auth`。

**Produces:** 动态 `web_search_opt_in_enabled`；remote search 四条件 fail-closed。

- [ ] 写/保留 feature 联动测试：default → env，admin PUT true → true，PUT false → false，finally 清理配置。
- [ ] 写参数化 handler 矩阵：

```python
@pytest.mark.parametrize(
    ("global_enabled", "user_opt_in", "local_answerable", "remote_calls"),
    [
        (False, True, False, 0),
        (True, False, False, 0),
        (True, True, True, 0),
        (True, True, False, 1),
    ],
)
async def test_web_search_authorization_matrix(
    global_enabled, user_opt_in, local_answerable, remote_calls
):
    tool = build_workflow_registry().get("xingchen.web_search")
    local_result = {"answerable": True, "data": {"chunks": []}} if local_answerable else None
    with patch(
        "app.butler.workflow_tools._local_kb_search",
        new=AsyncMock(return_value=local_result),
    ), patch(
        "app.butler.workflow_tools.run_workflow",
        new=AsyncMock(return_value=VALID_WORKFLOW_OUTPUTS["xingchen.web_search"]),
    ) as remote:
        context = _auth_ctx(
            db=AsyncMock(),
            global_enabled=global_enabled,
            user_opt_in=user_opt_in,
        )
        result = await tool.handler(context, VALID_INPUTS["xingchen.web_search"])
    assert remote.await_count == remote_calls
    assert result["available"] is (local_answerable or remote_calls == 1)

async def test_web_search_missing_auth_context_is_fail_closed():
    tool = build_workflow_registry().get("xingchen.web_search")
    with patch(
        "app.butler.workflow_tools._local_kb_search",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.butler.workflow_tools.run_workflow",
        new=AsyncMock(),
    ) as remote:
        result = await tool.handler(_ctx(db=AsyncMock()), VALID_INPUTS["xingchen.web_search"])
    assert result["available"] is False
    assert result["error_code"] == "confirmation_required"
    remote.assert_not_awaited()
```

- [ ] 最小实现保持：

```python
auth = context.web_search_auth
if auth is None or not auth.global_enabled or not auth.user_opt_in:
    return {
        "available": False,
        "source": "none",
        "degraded": True,
        "error_code": "confirmation_required",
        "data": {"refuse_reason": refuse},
    }
```

- [ ] 运行：

```powershell
cd D:\math-arena\services\api
.venv\Scripts\python.exe -m pytest -q tests/test_admin.py -k "FeaturesButlerLinkage or SystemButler"
.venv\Scripts\python.exe -m pytest -q tests/test_butler_workflow_tools.py -k "web_search"
```

Expected: user opt-in false 或本地可答时 remote await count 为 0。

### Task 3: 管理员 KB bench 权限与 citation 兼容层

**Files:** `kb_router.py`、`test_iter05_kb.py`、`test_m1_fixes.py`。

**Produces:** admin-only JWT 可访问 docs/chunks/retrieve/eval；import 权限不变；citation 可选字段无损重放。

- [ ] 用不带 student 的 admin-only JWT 写测试：

```python
token = create_token_with_role(
    user_id=str(user_id), role="admin", roles=["admin"], verified=True
)
```

- [ ] 显式权限：

```python
Depends(require_role("student", "teacher", "researcher", "admin"))  # retrieve
Depends(require_role("teacher", "researcher", "admin"))             # docs/chunks/eval
```

Keep `/docs/import` as teacher/researcher only.

- [ ] 保留 citation replay 断言：

```python
assert item["title"] == "导数概念"
assert item["url"] == "https://example.com/derivative"
assert item["snippet"] == "导数是函数的局部变化率……"
assert item["retrieved_at"] == "2026-08-21T10:00:00+00:00"
```

- [ ] 运行：

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_iter05_kb.py -k "KbAdminAccess"
.venv\Scripts\python.exe -m pytest -q tests/test_m1_fixes.py -k "replay_preserves_web_search_source_fields"
```

### Task 4: Admin 路由、布局、入口和权限守卫

**Files:** `AdminLayout.vue`、`AdminNav.vue`、`App.vue`、`nav.js`、`router/index.js`、`test/admin/router.test.ts`。

**Produces:** 六个 `meta.admin=true` 路由；admin 可发现入口；非 admin 无法进入。

- [ ] 路由结构测试：

```typescript
const paths = [
  '/admin/overview', '/admin/model', '/admin/xingchen',
  '/admin/cloud-kb', '/admin/kb-bench', '/admin/butler',
]
const adminRoutes = router.getRoutes().filter((r) => r.meta?.admin)
expect(new Set(adminRoutes.map((r) => r.path))).toEqual(new Set(paths))
```

- [ ] 测 root/guard：admin-only → `/admin/overview`；active teacher+admin → `/teacher/today`；student 访问 admin → `/overview`；无 token → `/login`。
- [ ] root 优先级：

```javascript
const roles = Array.isArray(u?.roles) ? u.roles.map((r) => r?.role) : []
if (active === 'teacher') return '/teacher/today'
if (roles.includes('admin')) return '/admin/overview'
return '/overview'
```

- [ ] AdminLayout 只有一个 RouterView，不带 teacher Butler panel 或 student right panel。
- [ ] 运行 `npx vitest run test/admin/router.test.ts`。

### Task 5: SecretField 与“空白保持、显式清除”安全语义

**Files:** `SecretField.vue`、`secretField.test.ts`、Model/Xingchen/CloudKb pages。

**Produces:** `SecretDraft { value: string, clear: boolean }`；PUT secret field 按意图 omitted/real/null。

- [ ] 定义 helper：

```typescript
export type SecretDraft = { value: string; clear: boolean }
export function secretPatch(draft: SecretDraft): string | null | undefined {
  if (draft.clear) return null
  const value = draft.value.trim()
  return value ? value : undefined
}
```

- [ ] 测试 blank → undefined、new value → string、explicit clear → null。
- [ ] SecretField 只展示 maskedValue；editable input 每次 GET 后为空：

```vue
<input v-model="draft.value" type="password" autocomplete="new-password" />
<span v-if="maskedValue">当前已配置：{{ maskedValue }}</span>
<label><input v-model="draft.clear" type="checkbox" />恢复环境默认</label>
```

- [ ] model primary/secondary、Xingchen api_key/api_secret、embedding api_key 均只在 `secretPatch(draft) !== undefined` 时写入 payload。
- [ ] cloud-kb 已有 masked credential 空输入必须 omit；显式 clear 才发送 `{key: null}`。
- [ ] 测试 masked string 永不出现在 PUT body，reload 后未编辑 secret 仍 configured。
- [ ] 运行 `npx vitest run test/admin/secretField.test.ts test/admin/pages.test.ts`。

### Task 6: 六页管理配置按真实后端契约闭环

**Files:** all `src/pages/admin/*.vue`、`HealthBadge.vue`、`src/api/index.js`、`test/admin/pages.test.ts`。

**Produces:** loading/empty/error/saving/testing；partial updates；health display。

- [ ] API 只补：

```javascript
getButler: () => api.get('/admin/system/butler'),
putButler: (payload) => api.put('/admin/system/butler', payload),
```

- [ ] Overview 展示 db/redis、channels、today calls、counts 和明确 error/empty。
- [ ] Model/Cloud KB/Embedding 的 test 按钮调用既有端点；HealthBadge 统一显示 ok/status、latency、error/message。
- [ ] Workflow 支持 enabled、flow_id、timeout 编辑：

```javascript
await adminApi.putWorkflow(wf.name, {
  enabled: wf.enabled,
  flow_id: wf.flow_id || null,
  timeout: Number(wf.timeout),
})
```

- [ ] 将“总开关仅环境变量可控”改为“环境变量为默认，可由全局配置覆盖”。
- [ ] Butler 页说明服务端能力开关不等于单条请求授权。
- [ ] KB bench 仅有 retrieve/docs/eval，不增加 import/delete。
- [ ] mount 六页，断言初始 GET、精确 PUT、test、loading/error 和无 masked secret。
- [ ] 运行 `npx vitest run test/admin/pages.test.ts`。

### Task 7: SourceCard、citation 和降级展示能力

**Files:** `SourceCard.vue`、`MessageBubble.vue`、`messageModel.js`、`messageModel.test.ts`、`sourceCard.test.ts`。

**Consumes:** `{n, source, loc, chunk_id, title?, url?, snippet?, retrieved_at?}` 与 degraded metadata。

**Produces:** safe source card；non-blocking degraded banner；history parity。

- [ ] 保留 full/legacy citation、degraded SSE、history block 测试。
- [ ] SourceCard 用单一 safeUrl：

```javascript
const safeUrl = computed(() => {
  try {
    const u = new URL(props.c.url)
    return ['http:', 'https:'].includes(u.protocol) ? u.href : ''
  } catch { return '' }
})
```

- [ ] icon 和 anchor 都只使用 safeUrl；invalid URL 只显示文本。
- [ ] 组件测试：

```typescript
expect(mount(SourceCard, { props: { c: legacySource } }).text()).toContain('教材')
expect(mount(SourceCard, { props: { c: fullSource, open: true } }).find('a').attributes('href')).toBe('https://example.com/')
expect(mount(SourceCard, {
  props: { c: { ...fullSource, url: 'javascript:alert(1)' }, open: true },
}).find('a').exists()).toBe(false)
```

- [ ] MessageBubble 降级条不能替换或隐藏本地答案。
- [ ] 不在本任务新增 agent-router degraded producer；测试明确标为 renderer-ready。
- [ ] 运行 `npx vitest run test/messageModel.test.ts test/sourceCard.test.ts`。

### Task 8: 管理端与搜索体验 E2E

**Files:** `e2e/phase6b-admin.spec.ts`。

**Produces:** browser-level navigation/save/test/permission/source evidence。

- [ ] 用 Playwright 路由模拟 API，不使用真实密钥：

```typescript
await page.route('**/api/admin/**', async (route) => {
  const path = new URL(route.request().url()).pathname
  const response = adminFixtureByPath[path] ?? { code: 40400, message: 'not_found', data: null }
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(response),
  })
})
```
- [ ] 管理员旅程：root → admin overview → 六导航 → Butler save exact booleans → masked state显示且输入为空 → test health。
- [ ] 权限旅程：student 访问 admin 重定向 overview，无 admin content flash。
- [ ] 来源旅程：答案保留、HTTPS source 可打开、invalid scheme 不可点击、degraded banner 可见。
- [ ] 运行：

```powershell
npm run e2e:mock -- e2e/phase6b-admin.spec.ts
```

### Task 9: 最终验证、范围扫描与提交门禁

**Files:** 只修复 File Map 内由验证证明的问题。

- [ ] 后端聚焦：

```powershell
cd D:\math-arena\services\api
.venv\Scripts\python.exe -m pytest -q tests/test_admin.py tests/test_butler_workflow_tools.py tests/test_iter05_kb.py tests/test_m1_fixes.py tests/test_butler_phase6a_prewiring.py
.venv\Scripts\ruff.exe check app/butler/workflow_tools.py app/gateway/agent_router.py app/gateway/kb_router.py tests/test_admin.py tests/test_butler_workflow_tools.py tests/test_iter05_kb.py tests/test_m1_fixes.py
```

- [ ] 后端完整 `.venv\Scripts\python.exe -m pytest -q`，记录 pass/fail/skip。不得在 6B 修 M3；任何 6B/M2 failure 是 No-Go，已知 M3 failure 单列且仍阻止“全仓绿”声明。
- [ ] 前端：

```powershell
cd D:\frontend
npm run test:run
npm run typecheck
npm run build
npm run e2e:mock -- e2e/phase6b-admin.spec.ts
```

- [ ] 安全/范围扫描：

```powershell
rg -n "verify_derivation|wf_verify_derivation|lean\." D:\math-arena\services\api\app D:\frontend\src
rg -n "api_key|api_secret|secret" D:\frontend\src\pages\admin D:\frontend\src\components\admin
git -C D:\math-arena diff --check
git -C D:\frontend diff --check
```

- [ ] 隔离 smoke：GET masked → 只保存非 secret → secret 不变 → explicit clear 才回退 env；只清理由 smoke 创建的 disposable config。
- [ ] 未经用户明确批准不得提交。批准后两个仓库分别暂存 File Map 路径，不暂存其他脏文件。

Suggested commits:

```text
feat: complete phase 6b admin controls and search authorization
feat: add phase 6b admin UI and source degradation experience
```

## 5. Acceptance Matrix

| Gate | PASS 条件 | 当前候选 |
|---|---|---|
| Scope | 仅 File Map；无 v2/F14/DB/M3 | Conditional PASS |
| Authorization | global + opt-in + local refusal；fail-closed | Candidate PASS，待全回归 |
| Feature flag | effective config 动态联动 | Candidate PASS |
| Admin access | 六页可发现；admin-only；非 admin 拒绝 | FAIL：root/显式 retrieve/测试待修 |
| Secret safety | masked never PUT；blank preserve；explicit clear | **FAIL / blocker** |
| Workflow config | enabled/flow_id/timeout 可编辑并测试 | FAIL：只支持 enabled |
| Source safety | full + legacy；URL allowlist | Partial FAIL：anchor 未统一 safe URL |
| Degraded UX | 保留本地答案；消费事件 | Renderer partial；live producer out-of-scope |
| Tests | admin route/page/secret/source + E2E | FAIL：缺组件/E2E |
| Build/typecheck | Vitest/typecheck/build/E2E 均绿 | 当前 54 Vitest + typecheck PASS；最终待重跑 |

## 6. Go / No-Go

- **计划进入实施：Conditional Go**，前提是用户批准，并接受“展示能力与在线切流分离”。
- **当前候选实现提交：No-Go**。最小阻塞项：SecretField 安全语义、admin root/guard 测试、workflow flow_id/timeout、SourceCard safe URL、admin/component/E2E tests。
- **宣称真实联网搜索闭环：No-Go / out-of-scope**。需等后续 v2 chat 场景迁移，补 tool result → citation/degraded SSE 的真实联调。

## 7. Self-Review Record

- Spec coverage：总计划 Task 9 规范来源、Task 10 有效配置/脱敏、Task 11 admin/搜索/降级均有任务。
- Placeholder scan：无 TBD/TODO/未定义接口；所有行为有文件、测试和命令。
- Type consistency：`web_search_opt_in_enabled`、`web_search_enabled`、`external_allowed`、来源四字段命名一致。
- Scope check：live web search/degraded producer 明确移出；KB admin 只限 bench read paths。
- Dirty-worktree safety：禁止 reset/checkout/clean/stash，提交只允许 File Map。

本文件仅为实施计划与范围审计；尚未授权实施或提交。
