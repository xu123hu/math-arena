# 智学数研统一登录注册与身份审核系统设计

日期：2026-08-22

状态：设计已逐节确认，等待书面规格复核

涉及仓库：`D:\math-arena`（FastAPI 后端）、`D:\frontend`（Vue 3 前端）

## 1. 背景与结论

智学数研当前已有学生端、教师端、科研端和管理员后台，但认证能力仍是开发版：短信验证码仅支持固定值，7 天 JWT 保存在 `localStorage`，refresh session、密码登录、账号恢复、角色审核中心和设备撤销均不存在。现有 `researcher` 角色可以自助自动通过；`teacher` 即使处于未验证状态，也可能因 JWT 中包含该角色而被只检查 `roles[]` 的接口放行。

本设计采用以下已确认结论：

1. 在现有 FastAPI 单体内新增边界清晰的 `identity` 领域，不引入 Keycloak 或云 CIAM。
2. 手机号验证码为主登录方式，密码为备用方式；未来学校 SSO、扫码登录通过 OIDC/provider 接口扩展。
3. 学生完成轻量首次引导后立即开通；教师和科研人员由管理员审核，也可凭机构邀请码自动批准。
4. 一个手机号对应一个统一账号，一个账号可以拥有多个角色；只允许切换到已批准角色。
5. Access token 为 15 分钟内存令牌，refresh token 为可轮换、可撤销的 HttpOnly Cookie。
6. 短信服务使用 provider 抽象；开发/比赛环境使用受控演示 provider，生产环境预留腾讯云短信 provider，未配置时拒绝发送。
7. 班级邀请码只负责已登录学生加入班级，不再创建 `class_*` 伪手机号账号。

## 2. 调研依据

调研显示，主流教育平台普遍把“认证”和“业务角色授权”分开：

- 国家智慧教育公共服务平台支持手机号/通行证 ID、密码、扫码和多身份，角色资料在账号建立后管理：<https://auth.smartedu.cn/uias/login>、<https://user.smartedu.cn/register>。
- Moodle 支持本地账号、OAuth 2、CAS、LDAP、SAML 和 MFA，并允许控制第三方登录是否自动创建账号：<https://docs.moodle.org/502/en/Manage_authentication>、<https://docs.moodle.org/405/en/OAuth_2_authentication>。
- Canvas 支持本地认证与多种 SSO provider，并将 JIT 账号创建和业务属性映射分开：<https://community.canvaslms.com/html/assets/Canvas_Admin_Guide.pdf>。
- OWASP 要求安全会话、token 轮换、重新认证和风险感知控制：<https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html>、<https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html>。
- NIST SP 800-63B-4 指出短信 OTP 不抗钓鱼，必须配合失败次数限制和风险控制：<https://pages.nist.gov/800-63-4/sp800-63b.html>。
- 腾讯云短信提供签名/模板、发送频控和防盗刷监控，生产 provider 需要映射其限频与供应商错误：<https://cloud.tencent.com/document/product/382/13303>、<https://cloud.tencent.com/document/api/382/38778>。
- 《个人信息保护法》第四十七条规定了应主动删除或个人可请求删除的适用情形，并允许在法定保存期未届满或技术上难以删除时仅进行必要存储和安全保护：<https://www.npc.gov.cn/npc/c2/c30834/202108/t20210820_313088.html>。
- 《网络安全法》第二十一条要求按规定留存相关网络日志不少于六个月；本系统的安全审计保留策略以此为下限：<https://www.cac.gov.cn/2016-11/07/c_1119867116_2.htm>。

因此，本期不把短信视为高权限管理员的唯一认证因素；管理员采用密码与短信的二次认证，并对审核操作要求近期重新认证。

## 3. 目标与非目标

### 3.1 目标

- 完成学生、教师、科研人员和管理员的统一登录、注册、恢复、会话和授权闭环。
- 建立教师/科研角色申请、补充资料、批准、驳回、停用和恢复流程。
- 修复未审核角色越权、科研角色自动通过、不可撤销 JWT、验证码重放和手机号枚举风险。
- 保留现有三端业务路由和角色隔离，提供平台级应用切换器。
- 提供开发环境可稳定演示、生产环境诚实降级的短信通道。
- 建立可自动验证的后端、前端和 E2E 门禁。
- 提供账号注销、个人信息删除请求和手机号换绑的完整生命周期能力。

### 3.2 非目标

- 本期不实现微信、QQ、App 扫码登录或真实学校 SSO。
- 本期不引入独立身份服务或第三方 CIAM。
- 本期不收集身份证号、身份证照片、家庭住址等高敏感资料。
- 本期不重构学生、教师、科研工作台的业务功能。
- 本期不让前端、JWT 或短信供应商成为角色授权事实源。

## 4. 总体架构

后端新增 `app/domains/identity/`，保持 router、service、repository/provider 和 model 边界：

```text
Vue Auth Center
  -> /api/auth/*                 登录、验证码、密码、刷新、退出、账号安全
  -> /api/identity/*             首次引导、角色申请、申请进度、组织邀请码
  -> /api/admin/identity/*       管理员审核、停用、恢复、审计查询
        |
        v
identity services
  account | credential | challenge | session | role application | authorization | audit
        |
        +-> PostgreSQL           账号、凭据、会话、角色、申请、组织、审计
        +-> Redis                OTP challenge、限流、风控、短期权限缓存
        +-> SmsProvider          demo | tencent
```

既有 `app.gateway.auth` 的公开依赖保持兼容入口，但内部委托给新的 authorization service。普通业务接口继续使用 Bearer access token；refresh、logout 和 CSRF 初始化使用受限 Cookie 流程。

## 5. 数据模型

### 5.1 users

保留现有用户 ID 和业务外键，增加：

- `status`: `active | suspended | disabled | deletion_pending`。
- `phone_verified_at`。
- `onboarding_status`: `required | completed`。
- `last_active_role`，只保存最近一次已批准普通业务角色。
- `security_version`，密码、手机号或全局安全状态变化时递增。

手机号继续保持唯一；日志、审计和 API 默认只返回掩码手机号。

### 5.2 user_credentials

- `user_id`。
- `credential_type`: 本期固定为 `password`，为未来 OIDC identity 预留扩展。
- `secret_hash`: Argon2id。
- `password_changed_at`。
- `failed_attempts`、`locked_until`。
- 唯一约束：`(user_id, credential_type)`。

### 5.3 auth_sessions

- `user_id`、`session_id`、`token_family_id`。
- `security_version` 快照。
- `device_name`、`user_agent_digest`、`ip_prefix`。IPv4 只保存 `/24`，IPv6 只保存 `/64`，不保存完整客户端 IP；安全事件确需更细粒度时必须另行评估并设置更短保存期。API 仅信任配置清单中的反向代理所写入的转发头，直连请求一律使用对端地址，客户端自带的 `X-Forwarded-For` 不参与风控或限流判定。
- `created_at`、`last_seen_at`、`idle_expires_at`、`expires_at`、`revoked_at`、`revoke_reason`。

### 5.4 auth_refresh_tokens

- `session_id`、`token_family_id`、`parent_token_id`。
- `token_hash`：带服务端 pepper 的 HMAC，绝不保存原文。
- `status`: `active | used | revoked`。
- `issued_at`、`used_at`、`expires_at`。
- 每次刷新插入新 token 并把旧 token 标为 `used`；已使用 token 的重放会撤销整个 family。

### 5.5 role_bindings

把 `verified: bool` 迁移为明确状态：

- `status`: `pending | approved | rejected | suspended`。
- `approved_at`、`approved_by`。
- `suspended_at`、`suspended_by`、`status_reason`。
- 唯一约束继续使用 `(user_id, role)`。

`verified` 在兼容窗口内仅作为派生字段返回，服务端授权不再读取它。

### 5.6 role_applications

- `user_id`、`role`: `teacher | researcher`。
- `status`: `pending | needs_more_info | approved | rejected | withdrawn`。
- `organization_id` 或申请时的组织名称快照。
- 教师资料：院系、工号、任教学段、学科。
- 科研资料：院系、工号/学号、研究方向。
- `evidence_file_id` 可选，只接受工作证/校园卡等必要证明。
- `invite_id` 可选。
- `submitted_at`、`reviewed_at`、`reviewed_by`、`review_note`。
- 同一用户同一角色最多存在一个进行中申请；重提生成新版本并关联前一申请。

### 5.7 organizations 与 organization_invites

`organizations` 保存学校/科研机构的规范名称、类型和状态。邀请码使用至少 128 位随机熵，编码后不少于 22 个 URL-safe 字符；数据库只保存 `HMAC-SHA-256(invite_pepper, invite)`，pepper 由部署 secret 注入并与数据库分离。`organization_invites` 还保存允许角色、有效期、使用次数上限、创建管理员和撤销状态。邀请码原文仅在创建时展示一次。兑换接口按账号、IP 和邀请码摘要限流，并对最后一次额度使用采用数据库原子更新。

### 5.8 identity_audit_logs

记录登录成功/失败、验证码发送/失败、密码变化、会话刷新/撤销、角色申请与审核。仅保存必要摘要、掩码手机号、IP 前缀和 request ID，不保存验证码、密码、token、证明材料正文或供应商密钥。

安全与网络审计日志热存储 90 天，之后转入加密、访问受控的归档并补足至少 180 天总保存期；到期后删除明细并只保留不可回溯个人的聚合指标。管理员身份审核记录默认保存 2 年，用于权限争议追溯；若适用的组织或法规要求不同期限，由数据分类表记录依据。证明材料在审核结束 30 天后删除，存在申诉时保留至申诉结束后 30 天。所有归档、查询和删除动作本身写审计。

### 5.9 学生首次引导与协议记录

既有 `student_profiles` 增加 `school_stage`、`grade` 和可选 `organization_id`；班级仍只由 `class_members` 表达，不允许学生在画像中自行声明班级。新增 `user_consents` 保存 `user_id`、协议类型、协议版本、同意时间和来源，不保存无关浏览行为。注册提交必须带当前服务协议与隐私政策版本，后端校验后写入记录。

### 5.10 account_deletion_requests

- `user_id`、`status`: `cooling_off | cancelled | processing | completed | blocked_by_retention`。
- `requested_at`、`execute_after`、`cancelled_at`、`completed_at`。
- `retention_basis`：仅在存在法定或组织留存义务时填写明确依据和到期时间。
- `result_digest`：记录删除/匿名化结果摘要，不保存已删除的个人信息正文。

注销采用 7 天冷静期。冷静期开始即撤销全部会话并停止普通业务处理；用户完成重新认证后可以在到期前取消。执行时删除手机号、邮箱、昵称、密码凭据、会话、角色申请和证明材料；学习、作业和审核记录按数据分类表执行物理删除、解除用户关联或不可逆匿名化。依法必须保留且期限未届满的数据只允许必要存储与安全保护，到期后由任务继续删除。注销后原手机号可以注册全新账号，但不得自动关联旧学习数据。

## 6. API 契约

### 6.1 认证

- `POST /api/auth/challenges/sms`：创建带 `purpose` 的短信挑战。
- `POST /api/auth/login/sms`：手机号、challenge ID、验证码、remember me。
- `POST /api/auth/login/password`：手机号、密码、remember me。
- `POST /api/auth/password/set`：已验证手机号的用户首次设置密码。
- `POST /api/auth/password/reset/challenge`、`POST /api/auth/password/reset`。
- `POST /api/auth/phone/change/old-challenge`、`POST /api/auth/phone/change/new-challenge`、`POST /api/auth/phone/change/confirm`。
- `POST /api/auth/token/refresh`：Cookie + CSRF，旋转 refresh token。
- `POST /api/auth/logout`、`POST /api/auth/logout-all`。
- `GET /api/auth/sessions`、`DELETE /api/auth/sessions/{session_id}`。
- `POST /api/auth/account/deletion`、`GET /api/auth/account/deletion`、`POST /api/auth/account/deletion/cancel`。
- `GET /api/auth/me`。
- `POST /api/auth/role/switch`：仅切换到 `approved` 角色并重新签发 access token。

旧 `/api/auth/sms-code` 和 `/api/auth/login` 在一个短兼容周期内调用新 service，前端迁移完成后删除；旧 `/api/auth/login-by-code` 停止创建账号，改为明确的弃用错误。

### 6.2 首次引导与角色申请

- `PUT /api/identity/onboarding/student`。
- `POST /api/identity/role-applications`。
- `GET /api/identity/role-applications/current`。
- `PUT /api/identity/role-applications/{id}`：仅 `needs_more_info` 或 `rejected` 可补充重提。
- `POST /api/identity/organization-invites/redeem`。
- 既有 `POST /api/classes/join` 保留，要求已登录且具有 `approved student` 角色。

### 6.3 管理员身份审核

- `GET /api/admin/identity/applications`：状态、角色、组织和时间筛选。
- `GET /api/admin/identity/applications/{id}`。
- `POST /api/admin/identity/applications/{id}/approve`。
- `POST /api/admin/identity/applications/{id}/reject`。
- `POST /api/admin/identity/applications/{id}/request-more-info`。
- `POST /api/admin/identity/roles/{binding_id}/suspend`、`/restore`。
- `GET /api/admin/identity/users`、`GET /api/admin/identity/users/{id}`。
- `POST /api/admin/identity/invites`、`GET /api/admin/identity/invites`、`DELETE /api/admin/identity/invites/{id}`。

管理员不能审核自己的申请。批准、驳回、停用、恢复和创建邀请码需要最近 10 分钟内完成二次认证。

## 7. 核心流程

### 7.1 短信登录与新账号

1. 客户端请求 `purpose=login` challenge。
2. 服务端先把手机号规范化为 E.164（界面默认 `+86`），再执行手机号、IP、设备和全局预算限流，必要时要求 CAPTCHA。
3. SmsProvider 发送验证码；客户端只收到 challenge ID、TTL 和重发时间。
4. 验证成功后销毁 challenge。已有用户创建 session；新用户创建统一账号并进入身份引导。
5. 学生完成昵称、学段、年级和协议确认后获得 `approved student`。
6. 教师/科研人员提交申请后进入审核状态页，不获得对应端权限。

### 7.2 密码登录与恢复

手机号验证成功后可以设置密码。密码使用 Argon2id，并执行以下统一规则：

- 长度为 15–128 个 Unicode code point，服务端按 NFC 规范化后完整校验且绝不截断。
- 允许空格、Unicode 和粘贴，兼容密码管理器；不强制大小写、数字、符号组合。
- 使用离线维护的常见、上下文相关和已泄露密码 blocklist；拒绝后给出可操作提示，但不把密码发送给外部查询服务。
- 不要求定期轮换；只有用户主动修改或存在泄露证据时强制更换。
- 密码失败采用统一文案、账号/IP 双维度递增等待和审计，不使用安全问题恢复。

忘记密码通过独立 `password_reset` challenge 完成，成功后递增 `security_version` 并撤销其他会话。该规则采用 NIST SP 800-63B-4 对单因素密码的 15 字符下限，而不是旧版指南的 8 字符下限：<https://pages.nist.gov/800-63-4/sp800-63b.html>。

### 7.3 手机号换绑与账号注销

正常换绑必须先验证旧手机号，再验证尚未绑定其他账号的新手机号；两个 challenge 绑定同一变更事务并在 15 分钟内完成。成功后更新手机号、递增 `security_version`、撤销全部会话并发送旧/新号码安全通知。无法使用旧手机号时不提供自动换绑，转入管理员辅助恢复：核对既有组织/班级关系，设置至少 24 小时等待期，由不同管理员复核并全程审计。

账号注销必须先近期重新认证，再创建 7 天冷静期请求。注销页明确列出立即停止、冷静期、删除/匿名化范围和依法保留范围；后台任务按 `account_deletion_requests` 执行并生成结果摘要。`deletion_pending` 用户可以完成认证，但只获得 `account_lifecycle` 受限 session，用于查看或取消注销和账号安全通知，不能访问学生、教师、科研或管理员业务接口。

### 7.4 管理员审核

管理员查看申请快照，执行通过、驳回或要求补充。批准事务同时更新 application 和 role binding、写审计、撤销该用户现有 session，并发送站内通知。有效机构邀请码走同一 service，以 `system_invite` 审核人类型留下记录。

### 7.5 多角色切换

登录不让用户预先声明高权限角色。后端返回所有角色状态和最近角色。只有一个已批准角色时直接进入；多个已批准角色时进入最近工作台，并由平台级应用切换器调用后端换发 access token。管理员入口独立，不出现在普通工作台默认切换列表。

### 7.6 班级加入与旧临时账号

班级码仅在已登录学生调用 `/api/classes/join` 时使用。已有 `class_*` 临时账号保留数据和班级成员关系；持有有效旧会话的用户进入一次性手机号绑定流程，绑定时合并到目标统一账号并保留学习数据。没有有效旧会话的临时账号由管理员辅助认领，不再允许仅凭班级码恢复。

## 8. Token、Cookie 与 CSRF

- Access token：15 分钟，仅在前端内存保存；claims 至少包含 `sub`、`sid`、`active_role`、`security_version`、`iat`、`exp`、`jti`。
- Refresh token：256 位以上随机值；默认 7 天，remember me 为 30 天；Cookie 名使用 `__Host-ma_refresh`（生产 HTTPS）。
- CSRF：refresh/logout 等 Cookie 认证写接口使用 double-submit token；CSRF token 可读但不含认证秘密。
- Refresh token 每次使用后轮换。刷新事务先按 token HMAC 定位 `auth_refresh_tokens`，再对 token 和 session 行执行 PostgreSQL `SELECT ... FOR UPDATE`；只有 `active` token 可以换发。并发请求中的第一个把旧 token 标为 `used` 并插入新 token，后续请求识别 `used` 状态后撤销整个 family。不得使用进程内锁代替数据库锁。
- 权限变更通过 session 撤销和短 access token 共同收敛；教师、科研、管理员高权限接口还要检查 Redis/数据库中的当前 binding 状态。
- 开发环境允许非 Secure 的本地域名 Cookie；生产环境启动校验必须要求 HTTPS、安全 JWT 密钥和明确 CORS allowlist。
- 普通 session 默认绝对有效期 7 天、空闲 24 小时；remember me 绝对有效期 30 天、空闲 7 天；管理员 session 绝对有效期 12 小时、空闲 30 分钟。每次成功 refresh 更新 `last_seen_at` 和 `idle_expires_at`，超过任一期限均不能续期。

短信 OTP 作为普通用户主登录方式属于明确接受的单因素、非抗钓鱼风险。为降低风险，新设备或显著变化的 IP 前缀会生成安全事件并在站内提示；短信 provider 可用时发送安全通知。学生账号在异常登录时追加 CAPTCHA 与新的 OTP challenge。已批准教师/科研人员在首次进入高权限端前必须设置密码，新设备或高风险登录要求密码和短信二次验证；管理员始终要求密码和短信。设备信任只保存随机、可撤销标识，不使用浏览器指纹作为唯一认证因素。

## 9. 短信挑战与供应商

`SmsProvider` 统一接口接收已渲染模板参数，不向业务层暴露供应商 SDK：

- `DemoSmsProvider`：只允许非生产环境；生成随机验证码。测试环境通过 dependency override 捕获验证码，UI 不显示固定码。比赛演示可由显式 `DEMO_SMS_ENABLED=true` 和手机号 allowlist 控制。
- `TencentSmsProvider`：预留 Secret ID/Key、SDK App ID、签名、模板 ID 和 region 配置；供应商错误映射为稳定业务码。
- 生产环境 provider 未配置或仍为 demo 时，应用拒绝发送并返回 `SMS_PROVIDER_UNAVAILABLE`。

验证码为加密随机六位数，5 分钟有效、一次性、最多失败 5 次。Redis 保存 `HMAC(challenge_id + phone + purpose + code)`、purpose、TTL 和失败次数。登录、重置密码、换绑手机号的 challenge 互不通用。

基础限流：手机号 60 秒一次；同时限制手机号/IP/设备的小时和自然日额度；达到风险阈值后要求 CAPTCHA。供应商还可施加更严格限制，前端统一显示可重试时间。

CAPTCHA 同样通过 `CaptchaVerifier` 抽象接入。开发/测试使用可注入 verifier；生产未配置 CAPTCHA provider 时，风险阈值以内的请求正常处理，达到阈值的请求直接返回 `AUTH_RATE_LIMITED`，不能为了可用性绕过风控。后续接入具体 CAPTCHA 服务只替换 verifier，不改变认证业务接口。

邀请码不走短信 challenge，但必须遵守账号、IP 和邀请码摘要三维失败限流。服务端只比较 HMAC 摘要，日志不记录邀请码原文；连续失败达到阈值后要求 CAPTCHA 或暂时拒绝。

腾讯云错误在 provider 层按类别映射，不允许业务层依赖供应商码：

| 供应商错误类别 | 稳定 `error_key` | HTTP/是否重试 | 用户行为 |
|---|---|---|---|
| 30 秒、小时、日频控 | `AUTH_RATE_LIMITED` | 429；按 `retry_after` | 等待后重试 |
| 手机号格式、地区或黑名单不可达 | `AUTH_DELIVERY_UNAVAILABLE` | 400；不可立即重试 | 检查号码或改用密码 |
| 签名/模板未审核、参数不匹配 | `SMS_PROVIDER_MISCONFIGURED` | 503；用户不可重试 | 运维告警，不暴露配置细节 |
| 套餐、应用或账号额度耗尽 | `SMS_PROVIDER_UNAVAILABLE` | 503；条件恢复后重试 | 改用密码，运维告警 |
| 网络、超时、供应商 5xx | `SMS_PROVIDER_UNAVAILABLE` | 503；服务端最多安全重试一次 | 稍后重试或改用密码 |
| 未知供应商错误 | `SMS_PROVIDER_UNAVAILABLE` | 503；默认不重试 | 记录脱敏 provider code |

## 10. 授权模型

新的授权依赖必须同时满足：

1. 账号 `users.status == active`。
2. access token 的 session 未撤销，`security_version` 匹配。
3. `active_role` 是接口要求的角色。
4. 对应 `role_binding.status == approved`。
5. 班级/项目等资源范围检查继续在业务 service 层执行。

不得用“角色存在于 `roles[]`”替代 active role 检查。待审核、被驳回或停用角色不能切换，也不能访问对应接口。前端路由守卫只是体验层，后端检查是安全边界。

`deletion_pending` 是普通业务授权的显式例外：仅账号生命周期路由接受带 `scope=account_lifecycle` 的受限 session，所有角色授权依赖仍按非 `active` 拒绝。

## 11. 前端信息架构与体验

### 11.1 统一认证中心

认证页使用响应式双栏布局：左侧呈现“数学知识图谱、可信验证、学生—教师—科研协作”的品牌价值；右侧为验证码/密码两个 tab。移动端折叠为单卡片。页面必须支持键盘、清晰焦点、非纯颜色状态和屏幕阅读器标签。

### 11.2 页面与路由

- `/auth/login`：验证码、密码、协议、找回密码。
- `/auth/onboarding`：新账号身份与资料引导。
- `/auth/application-status`：pending、needs more info、rejected 状态。
- `/account/security`：设置/修改密码、设备会话、退出全部设备。
- `/admin/identity/applications`：审核队列。
- `/admin/identity/users`：用户和角色状态。
- `/admin/identity/invites`：机构邀请码。

既有 `/login` 在迁移期重定向到 `/auth/login`。登录后只有一个可用角色时直接进入；多个角色按 `last_active_role` 进入，并提供应用切换器。

### 11.3 客户端认证状态

Pinia auth store 保存内存 access token、用户和角色状态。页面刷新时先调用 refresh 恢复会话，再拉取 `/auth/me`。`localStorage` 只保存非敏感界面偏好，不再保存 access token 或完整用户权限快照。401 只触发一次串行 refresh；失败后清理内存并带安全 redirect 返回登录页。

所有请求共享模块级 `refreshPromise` 单飞锁：第一个 401 创建 refresh Promise，其余 401 等待同一 Promise；成功后每个原请求最多重放一次，失败则统一退出。禁止每个组件或 API wrapper 各自刷新，避免 refresh token 轮换竞态。

### 11.4 CSP 与浏览器纵深防御

生产 Nginx 先以 `Content-Security-Policy-Report-Only` 盘点一轮资源，再转为强制策略。目标至少为 `default-src 'self'`、`script-src 'self'`、`object-src 'none'`、`base-uri 'self'`、`frame-ancestors 'none'`，`connect-src` 只允许同源 API/SSE 和明确配置的服务。禁止 `unsafe-eval` 和外部任意脚本；现有内联 style 迁移完成前可暂时保留 `style-src 'self' 'unsafe-inline'`，并单独跟踪收敛。认证页不加载第三方统计脚本，敏感响应增加 `Cache-Control: no-store`、`Referrer-Policy` 和 `X-Content-Type-Options`。

## 12. 稳定错误码

现有 API 信封的数字 `code` 保持不变，新增可选稳定字段 `error_key`。后端集中维护“数字 code ↔ error_key ↔ HTTP 状态”映射；前端优先依据 `error_key` 处理，兼容期内对旧接口保留数字 code 回退。成功响应仍为 `code=0`，不携带 `error_key`。至少提供以下稳定 key：

- `AUTH_CODE_INVALID`、`AUTH_CODE_EXPIRED`、`AUTH_CHALLENGE_PURPOSE_MISMATCH`。
- `AUTH_RATE_LIMITED`、`AUTH_CAPTCHA_REQUIRED`、`SMS_PROVIDER_UNAVAILABLE`。
- `AUTH_CREDENTIALS_INVALID`、`AUTH_SESSION_EXPIRED`、`AUTH_SESSION_REUSED`。
- `AUTH_CSRF_INVALID`、`REAUTH_REQUIRED`。
- `ACCOUNT_SUSPENDED`、`ONBOARDING_REQUIRED`。
- `ROLE_PENDING`、`ROLE_NEEDS_MORE_INFO`、`ROLE_REJECTED`、`ROLE_SUSPENDED`。
- `INVITE_INVALID`、`INVITE_EXPIRED`、`INVITE_EXHAUSTED`。
- `PHONE_CHANGE_CONFLICT`、`ACCOUNT_DELETION_PENDING`、`ACCOUNT_RETENTION_REQUIRED`。

认证失败使用统一外部文案，避免手机号枚举。供应商原始错误、堆栈、SQL、token 和密钥不得进入响应。

## 13. 管理员安全

管理员账号仍可由部署配置中的手机号 allowlist 引导，但首次进入必须设置密码并完成短信二次验证。后续管理员登录要求密码与短信，敏感审核动作要求最近 10 分钟的 re-auth 证明。管理员不能审核自身申请，不能通过普通角色申请获得 admin。管理员角色停用需要另一名管理员或受控运维流程，防止误锁唯一管理员。

受控运维恢复不提供公开 HTTP 端点。部署包提供仅能在受信运维环境执行的 `identity break-glass` CLI：默认禁用，启用时需要从标准输入提供独立部署 secret，目标必须是已验证手机号的现有账号；命令创建 15 分钟一次性管理员恢复 token、写入 append-only 安全审计并立即恢复为禁用状态。该审计不能由 CLI 删除，按管理员安全审计的 2 年策略保留。生产操作必须关联工单并由两人复核；CLI 不能直接修改业务角色或绕过数据库审计。

## 14. 迁移方案

1. 新建表和字段，保留旧列以支持短兼容窗口。
2. 学生 role binding 迁移为 `approved`。
3. `teacher verified=true` 迁移为 `approved`，否则为 `pending`。
4. 由于旧 researcher 是自动批准，普通 researcher 统一迁移为 `pending`；明确种子账号通过迁移 allowlist 标记为 `approved`。
5. admin 白名单账号迁移为 approved，但标记 `admin_mfa_setup_required`。
6. 部署新认证代码并拒绝不含 `sid` 的旧 JWT，所有用户重新登录。
7. 前端切换到内存 access token 和 refresh Cookie。
8. 停止 `/login-by-code` 创建账号，开放临时账号绑定/认领流程。
9. 兼容期固定为新认证生产发布后的 14 天或两个稳定发布版本，以先到者为准。旧端点每次调用写 deprecation 指标和结构化日志；截止后删除 `verified` 读取、旧 JWT 支持和旧认证端点，不允许通过配置无限延期。

Alembic upgrade、downgrade 和迁移后校验必须齐全。迁移脚本在变更 researcher 状态前输出数量统计；生产执行前先备份数据库。迁移不删除用户、学习数据、班级关系或 AI 产物。

## 15. 测试与验收

### 15.1 后端

- 单元：OTP HMAC、purpose 隔离、Argon2id、refresh 轮换/重放、角色状态机、邀请码。
- API：短信/密码登录、首次引导、重置、手机号换绑、账号注销/取消、刷新、退出、设备撤销、申请和审核。
- 权限矩阵：student、pending/approved/suspended teacher、pending/approved/suspended researcher、admin、suspended account。
- 并发：重复注册、OTP 双提交、同一 refresh token 并发、重复管理员审核、邀请码最后一次并发兑换。
- 迁移：upgrade/downgrade、旧角色映射、旧 JWT 拒绝、临时账号数据保留。
- 安全策略：15–128 字符密码、Unicode NFC、blocklist、无组合/定期轮换；新设备 step-up；idle/absolute timeout；注销数据分类执行。

### 15.2 前端

- 组件：手机号、OTP 分格输入、倒计时、密码强度、状态页、错误码映射。
- Store/client：启动 refresh、单飞刷新、401 重试一次、失败清理、角色切换。
- 路由：未登录、onboarding、pending、批准角色、多角色、管理员隔离。
- Playwright：学生注册；教师申请—管理员批准—重新登录；科研申请审核；角色切换；设备撤销。

### 15.3 安全与回归

- 验证 XSS 无法读取认证令牌、CSRF 拒绝、手机号不可枚举、OTP 暴力尝试受限、未审核角色越权失败。
- 验证强制 CSP 不阻断 Vue、KaTeX、SSE 和受控 API，且外部/内联恶意脚本被拒绝；Nginx 配置进入自动化 smoke test。
- 现有学生、教师、科研和管理员业务入口回归。
- 后端 pytest、静态检查，前端 Vitest、vue-tsc、生产 build 和关键 Playwright 全部通过。

### 15.4 必须可演示的验收场景

1. 学生短信注册并进入学生端。
2. 教师申请、管理员审核、重新登录进入教师端。
3. 科研人员经过相同审核后进入科研端。
4. 一个账号在多个已批准工作台间切换。
5. 未审核或停用角色被前后端同时阻断。
6. 设备会话撤销与旧 refresh token 重放阻断。
7. demo 短信通道正常；生产短信未配置时诚实返回不可用。

## 16. 配置与可观测性

新增配置使用明确前缀，不复用现有通用环境变量：

- `AUTH_ACCESS_TOKEN_MINUTES=15`
- `AUTH_REFRESH_DAYS=7`
- `AUTH_REFRESH_REMEMBER_DAYS=30`
- `AUTH_SESSION_IDLE_HOURS=24`
- `AUTH_SESSION_REMEMBER_IDLE_DAYS=7`
- `AUTH_ADMIN_SESSION_IDLE_MINUTES=30`
- `AUTH_SMS_PROVIDER=demo|tencent`
- `AUTH_DEMO_SMS_ENABLED=false`
- `AUTH_DEMO_SMS_ALLOWLIST=`
- `AUTH_TENCENT_SMS_APP_ID`
- `AUTH_TENCENT_SMS_SIGN_NAME`
- `AUTH_TENCENT_SMS_TEMPLATE_ID`
- `AUTH_TENCENT_SECRET_ID`、`AUTH_TENCENT_SECRET_KEY`
- `AUTH_CAPTCHA_PROVIDER=disabled|configured`
- `AUTH_INVITE_PEPPER`
- `AUTH_REFRESH_TOKEN_PEPPER`
- `AUTH_BREAK_GLASS_ENABLED=false`
- `AUTH_BREAK_GLASS_SECRET_HASH`
- `AUTH_CORS_ORIGINS`

密钥只通过部署 secret 注入，不进入前端、数据库、日志或提交。指标至少包括短信请求/成功/限流、登录成功率、密码失败、refresh 重放、活跃/撤销 session、待审核数量和审核时长。告警包括短信量异常增长、refresh 重放、管理员登录失败激增和待审核积压。

## 17. 实施边界

后端优先拆分认证领域，不继续扩张当前单文件 `auth_router.py`。前端不把所有状态塞回现有 `Login.vue`，而是建立认证页面、复用表单组件和集中错误映射。实施必须保护两个仓库当前未提交改动，只修改与认证直接相关的文件；每一阶段先写失败测试，再实现最小代码使其通过。

建议实施顺序：数据模型与迁移 → 立即修复授权漏洞 → challenge/password/session → 角色申请与管理员审核 → 前端认证中心 → 多角色/账号安全 → 手机号换绑与账号注销 → 历史账号迁移 → 全链验收。授权修复随第一份迁移同批发布，不等待完整认证 UI。
