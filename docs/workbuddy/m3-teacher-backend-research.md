# M3 教师端后端定向技术调研与 ADR

> 2026-08-21 使用 GitHub 连接器核验代表仓库；只借鉴模式，不引入依赖。

## 方向 1：教育 SaaS 与师生联动

核验 Moodle、Canvas LMS、Open edX。共同模式是课程/班级 scope、活动发布状态、学生尝试与教师评分分离、成绩变更可审计。适合本项目的是复用同一 Assignment/Submission 数据真相，以 `draft → published → closed` 控制学生可见；不适合照搬通用 LMS 的插件体系、微服务规模和整套权限模型。

## 方向 2：Agent 工作流与降级

核验 Dify、n8n、LangGraph。可借鉴 Provider 配置、错误分支、重试边界、checkpoint/HITL 和可观察性；不引入其运行时。M3 继续用 Butler Kernel，外部工作流只做一次结构化生成，失败转本地业务能力，发布/评分/课堂控制永远由本地状态机完成。

## 方向 3：教师工具与 Artifact

核验 WeBWorK/PG、H5P Editor，并结合 Khanmigo/MagicSchool/Brisk 的公开产品模式。可借鉴随机种子/答案重算、内容组件化、教师审核和从既有材料改编。M3 的落点是 Artifact 版本链、来源引用和确认闸；不引入 PG DSL、PHP 内容插件或供应商内部状态格式。

## 方向 4：课堂实时联动

商业 Kahoot、Mentimeter、Nearpod 没有可作为后端基座的官方开源仓库；GitHub 搜索主要返回非官方 clone，因此只采用稳定产品模式：教师拥有课堂 session 状态，学生只读当前有效状态，TTL/心跳决定过期，断网返回 degraded/unknown，绝不伪造参与度。实现仍基于现有 FastAPI + PostgreSQL 轮询契约。

## ADR

### ADR-01：单一业务数据真相

- 决策：教师和学生复用 M2 Assignment/Submission/Class 表。
- 理由：避免发布、成绩和课堂状态双写分叉。
- 替代：新建 teacher_assignment；拒绝。
- 影响：教师写路径需兼容 M2 学生读取。

### ADR-02：SystemConfig 作为工作流配置存储

- 决策：扩展现有 `system_configs["workflows"]`，不新增平行密钥体系。
- 理由：已有 Fernet、管理员鉴权和有效配置解析链。
- 替代：专用 `workflow_configs` 表；当前规模下收益不足。
- 影响：保留 `flow_id/timeout` 旧别名并增加规范字段。

### ADR-03：外部工作流是 Provider

- 决策：Butler/领域服务持有权限、状态和确认权；工作流只返回候选内容。
- 理由：可降级、可审计、不形成双内核。
- 替代：Dify/LangGraph 接管业务状态；拒绝。
- 影响：Adapter 必须做输入/输出映射和错误规范化。

### ADR-04：课堂状态用 TTL 记录

- 决策：教师写 ClassroomMode，学生经 scope 校验读取未过期状态。
- 理由：轮询简单可靠，服务重启后状态仍可恢复。
- 替代：仅内存 WebSocket session；拒绝作为唯一真相。
- 影响：实时人数是可选聚合；无数据时明确 degraded。

### ADR-05：19 个明确 teacher tools

- 决策：按 SSOT 的 7 读 + 7 生成 + 5 写注册 19 个工具。
- 理由：名称表是明确契约，优先于主提示词中冲突的“21”数字。
- 替代：凭数量新增未定义工具；拒绝。
- 影响：验收按名称集合、角色、scene、risk、确认和幂等检查。
