# 统一登录注册系统实施验证报告

- 验证日期：2026-08-22
- 后端分支：`codex/unified-auth-backend`
- 前端分支：`codex/unified-auth-frontend`
- 结论：计划内的身份模型、登录注册、角色审核、会话安全、账号生命周期、前端恢复路径及认证浏览器验收均已实现并通过本地自动化验证。

## 1. 实施提交

### 后端与部署

| 提交 | 内容 |
| --- | --- |
| `c4d0366` | 统一身份数据模型与 Alembic 迁移 |
| `f1476b8` | 基于数据库批准状态的五重授权校验 |
| `0bfa616` | 短信挑战、purpose 隔离、限流与 provider 边界 |
| `d35bd77` | Argon2id 密码登录、设置和重置 |
| `e63e250` | Refresh token 轮换、重放撤销与会话管理 |
| `42b59a9` | 短信登录、学生原子注册与 onboarding |
| `fd3885a` | 教师/科研人员申请及管理员审核 |
| `52bad2e` | 手机换绑、账号注销、审计保留与 break-glass |
| `cbd6f89` | CSRF、服务端管理员重认证、部署配置与跨栈安全收尾 |
| `11b5935` | 注销敏感操作改用服务端会话重认证时间 |
| `a125b77` | 兼容登录适配到可撤销会话，同时保留旧 `data.token` 响应 |

### 前端

| 提交 | 内容 |
| --- | --- |
| `796860b` | 内存 Access token、单飞刷新和冷启动 bootstrap |
| `8a243d2` | 短信/密码登录、注册、学生 onboarding、角色申请 |
| `db919b0` | 路由守卫、账号安全、管理员审核与 CSP |
| `eb7e39a` | 跨栈认证 mock 与首批浏览器验收 |
| `f516453` | 密码恢复、双验证码换绑、会话撤销、注销取消及完整 E2E |

## 2. 规格映射与自动化证据

| 设计域 | 已验证行为 | 主要证据 |
| --- | --- | --- |
| 身份与迁移 | 四态角色绑定、`security_version`、会话/凭据/审计表、旧 researcher 默认降为 pending、种子白名单保留 approved | `test_identity_models.py`、`test_identity_migration.py` |
| 授权 | 账号状态、会话撤销、security version、active role、approved binding 五重校验；pending/suspended/revoked 拒绝 | `test_authorization.py`、M3 scope 回归 |
| 短信挑战 | 单次消费、purpose 隔离、5 次失败锁定、过期、手机号限流、真实 Redis 并发双提交仅一次成功 | `test_sms_challenges.py` |
| 密码 | NIST 风格长度边界、弱密码阻断、Unicode/空格、Argon2id、重置后撤销会话、未知手机号通用响应 | `test_passwords.py` |
| 会话 | 15 分钟 Access token、哈希 Refresh token、轮换、family 重放撤销、并发刷新、idle/absolute timeout、CSRF | `test_sessions.py` |
| 学生注册 | 首次短信登录原子创建 student，重复/并发不产生重复用户，完成 profile 与 consent | `test_login_onboarding.py` |
| 专业身份 | 教师/科研申请 pending、禁止自审、管理员近期重认证、批准/驳回/补材料 | `test_role_applications.py`、`test_identity_admin.py` |
| 账号生命周期 | 双验证码换绑、会话撤销、7 天注销冷静期、取消、到期匿名化、手机号可重新注册 | `test_account_lifecycle.py` |
| 运维治理 | 180 天以上审计保留、双人 break-glass 开关、生产占位 pepper/demo provider 拒绝 | `test_break_glass.py`、`test_auth_config.py` |
| 前端安全 | Access token 仅内存、401 单飞刷新、CSRF header、角色守卫、恢复页面、CSP | Vitest auth suites、源码扫描、`nginx.conf` |
| 浏览器验收 | 学生注册/onboarding、教师申请、管理员审核与教师重新登录、科研审核、rejected/suspended 拒绝、角色切换、密码重置、会话撤销、手机号换绑、注销取消 | `e2e/auth.spec.ts` 12/12 |

## 3. 新鲜验证结果

| 验证项 | 结果 |
| --- | --- |
| `pytest tests/identity -q` | 72 passed |
| identity + 完整 `test_api_integration.py` 联合回归 | 91 passed，2 skipped |
| 核心 auth/admin/classroom 回归 | 46 passed |
| 15 个 M3 文件逐文件独立进程运行 | 82 passed |
| Alembic upgrade/downgrade/upgrade | 1 passed |
| Ruff（全部本次后端改动及 identity tests） | passed |
| `pip check` | No broken requirements found |
| 前端 `npm test` | 68 passed |
| 前端 `npm run typecheck` | passed |
| 前端 `npm run build` | passed；仅保留既有 router 静态/动态导入分包警告 |
| Playwright `e2e/auth.spec.ts` | 12 passed |
| `src` token 持久化扫描 | 无 `ma_token`、localStorage/sessionStorage token 读写 |
| CSP 静态检查 | Report-Only 与 enforced policy 均包含 `object-src 'none'`、`base-uri 'self'`、`frame-ancestors 'none'` |

M3 测试必须逐文件启动独立 pytest 进程。一次性把全部 M3 文件放入同一进程会触发现有 Windows asyncio/SQLAlchemy 跨事件循环连接池复用问题；相同 82 项在隔离进程中全部通过。

### 全仓测试诊断

按完成分支门禁额外运行了后端全仓 `pytest -q`：`1246 passed, 11 skipped, 100 failed, 37 errors`。首个与本次认证直接相关的旧 `/auth/login` → `/auth/role/switch` 回归已修复为 `a125b77`，其独立测试及完整 API integration 联合回归均通过。

其余失败在长会话中出现共享 `test_math_arena` schema 缺失（例如 `mastery_records` 表、`users.phone_verified_at` 列）并级联到 M2 学生流水、组卷、苏格拉底解题等旧模块，同时伴随 Windows asyncio/asyncpg 连接跨循环关闭异常。相同认证、M3 和迁移测试在独立干净进程均为绿。该全仓测试隔离问题不属于本次认证功能范围，但根据完成分支门禁，本分支不得自动合并，需先专项修复测试库生命周期或在 CI 中采用可靠隔离策略。

## 4. 迁移数据核对

迁移测试在全新 PostgreSQL 数据库先升级到 `m3_002_fullstack_closure`，实际插入以下数据，再升级到 `auth_001_unified_identity`：

| 数据 | 升级前 | 升级后 | downgrade 后仍保留 |
| --- | ---: | ---: | ---: |
| users | 4 | 4 | 4 |
| role_bindings | 4 | 4 | 4 |
| classes | 1 | 1 | 1 |
| class_members | 1 | 1 | 1 |
| events（学习行为） | 1 | 1 | 1 |

角色结果：student approved、teacher approved、普通历史 researcher pending、配置白名单 researcher approved。随后 downgrade 到 `m3_002_fullstack_closure` 并重新 upgrade 到 head 均成功。

生产执行前仍必须先做数据库备份和真实数据数量快照。回滚命令：

```powershell
python -m alembic downgrade m3_002_fullstack_closure
```

回滚会移除新认证会话、Refresh token、申请、同意记录等新表/字段；必须在维护窗口内执行并保留备份。

## 5. 安全探针结果

- OTP 重放、purpose mismatch、过期、锁定、Redis 并发消费：通过。
- Refresh 并发轮换、已使用 token 重放、family 撤销：通过。
- CSRF cookie/header 不一致拒绝；Refresh HttpOnly、CSRF 非 HttpOnly 且 Path `/`：通过。
- pending/suspended 角色、撤销会话、security version 不匹配、token/session active role 不一致：拒绝通过。
- 邀请码最后一次并发兑换：仅一次成功。
- 密码重置对已注册与未注册手机号返回相同成功信封：通过。
- 管理员审核与用户注销均只信任服务端 `AuthSession.reauthenticated_at`；伪造 `X-Reauth-At` 无效。
- 生产启动拒绝 demo 短信、开发/示例 pepper 和不足 32 字符的 pepper：通过。
- Access token 不进入浏览器 localStorage/sessionStorage：单元、E2E 与源码扫描通过。

## 6. 外部限制与上线前动作

以下内容按实施计划明确留在部署集成范围，本报告不声称已完成实网验证：

1. 腾讯云短信领域适配器和稳定错误映射已存在，但真实 SDK sender、签名、模板及生产凭证尚未接线；未接线时返回 `SMS_PROVIDER_UNAVAILABLE`，不会降级到 demo。
2. CAPTCHA 仅提供配置入口，具体生产供应商未实现；SSO、二维码登录和邮件登录不在本次范围。
3. E2E 使用本地 mock provider，不代表腾讯短信送达率或供应商限流验收。
4. CSP 当前仍允许 `style-src 'unsafe-inline'`；脚本、对象、base URI 与 framing 已收紧，后续应在样式迁移完成后移除 inline style 例外。
5. 仓库原有 M3 前端 Playwright 用例含已过期页面文案/选择器；认证验收套件独立 12/12 通过，但旧 M3 UI 套件需在其专项迭代中更新。

上线前必须完成：接线并实测腾讯短信、配置随机 JWT/三类 pepper、设置真实 demo allowlist 为空、确认可信代理网段、执行备份与迁移演练、检查审计归档任务。

## 7. 兼容窗口

旧 `/api/auth/sms-code` 与旧登录兼容入口只保留到 **2026-09-05**。兼容期内记录 deprecation 指标；到期删除旧端点和 `AUTH_ALLOW_LEGACY_TOKENS` 兼容路径，避免旧 7 天 JWT 长期残留。
