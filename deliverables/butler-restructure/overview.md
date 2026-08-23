# AI 管家化重构 · 交付总览

> 日期：2026-08-14　基于《AI 管家化重构总方案 v3.0》

## 已交付（后端先行 + 前端最短闭环）

按「先搭中枢骨架 → 逐个模块接入」渐进式原则，后端 AI 管家中枢 + 数据库扩展 + 关键接口 AI 化 + 前端右栏管家面板已落地，**后端 `import app.main` 通过、前端 `npm run build` 通过**。

### 1. AI 管家核心模块 `app/butler/`（新增 7 文件）
- `event_bus.py` 事件总线（幂等落库 `learning_events`）
- `tools.py` 工具集（学情/错题/出题/图谱/路由 7 工具）
- `state.py` 状态记忆（`student_profiles` 长期画像 + Redis 短期态）
- `llm.py` LLM 生成层（缓存 + 10s 超时 + 回退）
- `orchestrator.py` 调度器（事件 → 决策 → 技能 → 落库）
- `skills.py` 管家技能（今日计划/周报/错因诊断/路径规划）
- `gateway/butler_router.py` 10 个 HTTP 端点

### 2. 数据库扩展（4 张新表 + 1 张改表）
- `student_profiles` / `learning_events` / `ai_recommendations` / `exam_papers`(+`items`)
- `daily_questions` 改「每生每天一题」

### 3. 关键接口 AI 化
- `growth/today-3`：+ `ai_title`/`ai_why`/`ai_benefit`/`ai_intro`/`ai_encourage`
- `growth/overview`：+ `butler_message`
- 判分事件 `learning-events` → 自动上报管家中枢

### 4. 每日一题学情化（P0-2）
- 废弃 `date.toordinal()%len` 静态轮换，改为薄弱点 Top 加权轮换（每生每天一题）

### 5. 顺带修复既有隐藏 bug
- `growth_router._polish_copy` 缺失 `settings`/`get_model_router` 导入（翻转开关后会 500），已补

### 6. 前端接入（`D:\frontend`，zhixue-shuyan-v4，端口 5176）
- `src/api/index.js`：新增 `butlerApi`
- `src/pages/student/ErrorsView.vue`：「AI 问诊 · 错因」由规则模板升级为接 `/butler/error-diagnosis/{id}`（根因/口诀/建议，异常回退规则模板）
- `src/pages/student/ReportView.vue`：顶部加「🗞️ 小婷的周报」卡（接 `/butler/weekly-report` narrative + 数据脚注）
- 注：`D:\frontend` 已有右侧全局面板（`V4Layout.vue` 的 right-panel，已接 `growth/panel`），无需新建 ButlerPanel

## 交付物
| 文件 | 说明 |
|------|------|
| `deliverables/butler-restructure/db-migration.sql` | 可直接执行的数据库变更 SQL |
| `deliverables/butler-restructure/api-integration-matrix.md` | 前后端接口联调对照表 |
| `deliverables/butler-restructure/butler-architecture.md` | AI 管家架构说明与调用流程 |

## 验证结果（端到端实测）
- ✅ 后端 `import app.main` 通过，OpenAPI 125 路径，管家 10 端点全部注册
- ✅ 后端 ruff 无 F 级错误（仅 2 条 SIM105 风格建议）
- ✅ 前端 `D:\frontend` `npm run build` 通过（2.24s）
- ✅ 数据库迁移执行成功：5 张新表建好，`daily_questions` 重建加 `user_id`
- ✅ 后端 uvicorn 启动，`/api/health` OK
- ✅ 登录测试账号实测：`dashboard` / `today-3`（含 `ai_title` 等）/ `overview`（`butler_message`）/ `weekly-report`（`narrative`）/ `path-plan` / `recommend` 全部 `code:0`
- ✅ **LLM 链路真实工作**：周报/开场白/鼓励语均为 AI 生成自然语言（非模板）；空学情账号正确降级空态

## 待办（下一步）
- 前端逐页接入：OverviewView 的 today-3 优先用 `ai_*` 字段、图谱路径、对话页跳转
- 试卷题库套卷数据导入（模型与 SQL 已就绪）
- APScheduler 定时 worker（FSRS 到期主动推送）
