# M3 教师端后端审计与重建结论

> 审计日期：2026-08-21；重建复核：2026-08-22
> 审计基线：`d453235`；阶段 6 交接提交：`5054325`。
> 范围：`services/api/app/domains/teacher`、M3 模型/迁移、管理员工作流面、Butler Kernel、M2 学生联动、`D:\frontend` 只读契约。

## 1. 现有代码清单与完成度

| 区域 | 文件/目录 | 职责 | 结论 |
|---|---|---|---|
| 教师路由 | `app/domains/teacher/router.py` | 33 条路径 / 37 个操作、统一响应、依赖注入 | 主链可运行；已补 `POST /api/teacher/butler/chat` |
| 权限 | `scope.py` | active role、owner/confirmed teacher class scope、404 防枚举 | 可复用；负向测试已覆盖 |
| Artifact | `artifacts.py` | draft/confirmed/published/archived、版本、幂等、审计 | 可复用；聚焦测试通过 |
| 业务服务 | `today.py`、`insights.py`、`lessons.py`、`assessment.py`、`grading.py`、`classroom.py`、`resources.py` | 7 工作台后端 | P0 大部可复用；资源处理和部分降级仍是最小实现 |
| Capability | `capability_gateway.py`、`workflow_adapter.py` | 7 能力、数据库驱动星辰/本地切换 | 已实现 configured/verified/available 闸门、per-flow 配置和真实降级标记 |
| Butler | `registry.py`、`router.py` | 7 读 + 7 生成 + 5 写，共 19 个明确工具 | 名称、风险分层和 ButlerPanel chat 已对齐 SSOT |
| 数据 | `models/teacher.py`、`models/coursework.py` | Artifact、Insight、Action、Task、课堂模式及 M2 表扩展 | 可复用；工作流配置复用 `system_configs` 更合适 |
| 迁移 | `alembic/versions/m3_001_teacher_core.py` | M3 表和兼容扩展 | 单 head；隔离 PostgreSQL 已 upgrade 到 `m3_001_teacher_core` |
| 测试 | `tests/test_m3_teacher_*.py` | M3 聚焦测试 | 当前 68/68；覆盖工作流配置、Redis 故障容错、Butler chat 和学生课堂读取 |

## 2. 问题分类

### 架构

- 教师域已与学生 `agent_router.py`/`workflow_tools.py` 隔离，这是正确基础。
- `teacher/router.py` 与 `gateway/admin_router.py` 都已成为巨型路由；新增配置逻辑应下沉到独立服务，不继续堆业务细节。
- 没有第二套 Agent Runtime，Butler Kernel 的 Contracts/Registry/Policy/Ledger 可继续复用。

### 契约

- 前端实际调用的 Today、Artifact、Lesson、Quiz、Assignment、Grading、Classroom、Resource 路径均已存在；GET classroom 状态和 multipart 上传已对齐。
- 前端 `POST /api/teacher/butler/chat` 已有后端入口，输入严格限制为 scene/class/artifact/message/clientRequestId 等公开字段，不能注入 provider、workflow 或 tools。
- 管理员工作流已具备列表、单项、创建、更新、删除、测试、启用、禁用 8 个动作，并返回 configured/verified/available 三态。
- 主提示词“至少 21 个工具”与其明确清单矛盾；清单和技术 SSOT 都是 19 个，因此以 19 个命名工具为准。

### 数据

- M3 没有平行 Assignment/Submission 表，正确复用 M2。
- 工作流配置当前只在 `system_configs["workflows"]` 保存 `flow_id/timeout`；可扩展该 KV，不必再建平行表。
- `preprocess_course`、`understand_document` 的本地内容仍是最小空结构，不能表述为完整解析质量已交付。

### 安全

- active role 绕过、grading detail 跨班读取、Capability 任意 scene/class 等旧 Critical 已在当前 HEAD 修复并有测试。
- 每工作流 API Key/Secret 均使用 Fernet 密文持久化，响应只给掩码/是否已配置，不返回原值。
- 资源上传未绑定 class_id，当前只能证明 owner 隔离，不能证明班级共享资源边界。

### 降级

- 7 Capability 都有本地 builder；工作流未配置、禁用、未验证、超时或 Schema 非法时走本地结果，并明确 `degraded=true`。
- 工作流 Adapter 从 `system_configs["workflows"]` 读取 per-flow 地址、凭证、映射、超时与重试；配置变更会使验证状态失效。
- 上游异常已规范化，不透传原始响应。

### AI 管家

- Teacher Registry 与 student Registry 隔离，19 个工具均为 teacher-only。
- Capability HTTP 入口已走 Registry/Policy 校验并写 AgentRun/ToolInvocation。
- ButlerPanel chat 复用 Butler Kernel 的 Registry/Policy/Executor/Planner/Runtime；教师角色固定，class/artifact scope 在入口与 handler 两层校验。
- 生成类工具标记为 `LEARNING_ACTION`，正式写工具标记为 `WRITE`；WRITE 不直接执行，而返回 `confirmation_required`。

### 测试

- 当前 M3 聚焦测试 68/68；原 Artifact 7 例失败根因是 pytest-asyncio fixture 跨 loop，已用 function loop 修复。
- 已补管理员 8 动作契约、凭证密文、三态健康、数据库配置驱动 Adapter、学生课堂读取和 Butler chat 测试。
- 隔离 PostgreSQL 已执行完整 Alembic upgrade 并运行官方知识点种子，测试初始化可复制 5 个真实知识点。
- OpenAPI 在 M3 开启时为 33 条教师路径 / 37 个操作；加学生 `GET /api/classes/{class_id}/classroom-mode` 后共 34 条相关路径 / 38 个操作。M3 默认关闭时不挂载教师路径。

## 3. 可复用评估

保留：M3 模型和迁移主体、TeacherScope、Artifact 状态机、Today/Insight SQL、Lesson/Assignment/Grading 主链、Classroom TTL、Resource owner 模型、19-tool Registry、Butler Policy/Ledger。

本轮模块级重建已完成：工作流配置/Adapter、Butler chat、学生课堂状态读取和本地降级真实性。资源异步解析质量仍保持现有最小实现，不把空结构包装成完整解析能力。

## 4. 重建策略

采用“保留核心、模块级重建缺口”的增量策略，不推倒 5,000 余行已通过测试的 M3 实现：

1. 扩展 `system_configs["workflows"]`，兼容旧字段并实现教师 7 工作流完整配置模型。
2. 管理员路由保持原 M2 GET/PUT/test 合约，新增缺失动作和三态状态。
3. Adapter 从数据库读取配置；未配置、未验证、禁用、超时和 Schema 非法均走本地降级并正确标记。
4. 补 Butler chat 与学生课堂读取，不修改学生聊天语义。
5. 用真实 PostgreSQL、OpenAPI、前端只读契约和全量 pytest 验收。
