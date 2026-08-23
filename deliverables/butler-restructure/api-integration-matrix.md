# 前后端接口联调对照表

> 项目：智学数研 · AI 管家化重构（迭代17）　日期：2026-08-14
> 后端基址：`http://localhost:8000`　前端：`D:\math-arena-test-frontend`（Vue 3 + Vite）
> 信封约定：成功 `{code:0, message:"ok", data:...}`；失败 `{code:xxxxx, message:"..."}`

## 一、AI 管家新增端点（`/api/butler/*`，前端新增接入）

| # | 方法 | 端点 | 用途 | 前端消费点 |
|---|------|------|------|-----------|
| B1 | POST | `/api/butler/events/emit` | 业务模块上报学习事件（判分/错题/登录） | 判分提交后由后端内部调用（`learning-events` 已挂），前端一般无需直调 |
| B2 | GET | `/api/butler/dashboard` | 管家面板聚合：开场白 + 今日任务 + 到期错题 + 薄弱点 + 鼓励语 | 右侧全局面板（ButlerView / 右栏） |
| B3 | GET | `/api/butler/daily-plan` | 今日 3 件事（LLM 生成版） | 首页任务区三卡 |
| B4 | GET | `/api/butler/weekly-report` | 周报「小婷的话」+ 数据块 | 学情报告页顶部 AI 解读卡 |
| B5 | GET | `/api/butler/error-diagnosis/{record_id}` | 错题 AI 错因诊断（根因/口诀/建议） | 错题本详情页错因卡 |
| B6 | GET | `/api/butler/path-plan` | 学习路径规划（薄弱点 + 前置依赖） | 知识图谱 / 学习路径视图 |
| B7 | GET | `/api/butler/recommend` | 资源/变式推荐（薄弱点驱动） | 资源推荐卡片 |
| B8 | GET | `/api/butler/actions` | 最近管家动作（轮询/首屏） | 主动推送卡片流 |
| B9 | POST | `/api/butler/actions/{id}/feedback` | 学生反馈（accept/reject/skip） | 推送卡点击反馈 → 数据飞轮 |
| B10 | GET/PATCH | `/api/butler/settings` | 管家推送设置（学生可关） | 个人中心 AI 推送开关 |

## 二、既有接口 AI 化增强（前端字段对接）

| 模块 | 端点 | 新增/变更字段 | 前端消费点 |
|------|------|--------------|-----------|
| 学情总览 | GET `/api/student/growth/overview` | `butler_message`（管家消息「小婷的话」） | OverviewView 顶部 AI 解读 |
| 今日 3 件事 | GET `/api/student/growth/today-3` | 组1 每件事 `ai_title`/`ai_why`/`ai_benefit`；顶层 `ai_intro`/`ai_encourage` | 首页任务区（优先 `ai_*`，缺失回退原 `title`/`why`） |
| 全局面板 | GET `/api/student/growth/panel` | `encouragement` 已走 LLM 润色（`growth_llm_polish` 翻转 ON） | 右栏鼓励语 |
| 薄弱点分析 | GET `/api/student/report/weak-points` | `ai_reason` 已走 LLM 润色 | ReportView 薄弱点卡片 |
| 每日一题 | GET `/api/student/practice/daily` | 选题学情化（薄弱点 Top，不再全站同题） | 首页每日一题 |
| 开练（daily 模式） | POST `/api/student/practice/start` | 每日一题改为「每生每天一题」+ 学情选题 | 练题中心 |
| 判分事件 | POST `/api/student/learning-events` | 判分后自动上报管家中枢（内部，无响应变化） | 无（事件驱动） |

## 三、既有复用端点（前端维持现状，管家/页面共用）

| 模块 | 端点 | 说明 |
|------|------|------|
| 错题本 | GET `/api/student/error-records`、`/error-records/review-plan`、`/error-records/{id}/detail`、`/error-records/filter`、`/error-records/due-queue`、`/error-records/memory-heatmap` | FSRS 热力图 + 到期队列 |
| 学情报告 | GET `/api/student/report/highlights`、`/report/mastery-trend-forecast`、`/report/error-distribution`、`/report/honesty` | 亮点/趋势/12 类错因/诚实提示 |
| 知识图谱 | GET `/api/student/knowledge-graph`、`/knowledge-graph/nodes/{kp_code}`、`/knowledge-graph/tree`、`/nodes/{kp_code}/deps`、`/nodes/{kp_code}/recommend` | 图谱树/节点/依赖/推荐 |
| 模拟考试 | POST `/api/student/exam/generate`、GET `/api/student/exam/history`、GET `/api/student/exam/{id}` | 组卷/历史/详情（判分复用 `practice/submit`） |
| 对话 | POST `/api/agent/chat`（SSE） | 引导式对话核心逻辑（保留不变） |

## 四、前端页面 → 接口映射（改造目标）

| 前端页面/组件 | 数据接口 | 改造动作 |
|--------------|---------|---------|
| 右侧全局面板（ButlerPanel） | `/butler/dashboard` + `/growth/panel` | 今晚任务/今日行动/鼓励语全部接 `dashboard`，不再静态写死 |
| 侧边栏待办角标 | `/butler/dashboard`（`due_errors` 数）+ `/student/assignments` + `/student/warnings` | 红点由 AI 待办 + 教师任务 + 预警三类驱动 |
| 学情总览 OverviewView | `/growth/overview`（`butler_message`） | 顶部加「小婷的话」AI 解读卡 |
| 今日 3 件事 | `/growth/today-3`（`ai_*` 字段） | 卡片标题/原因/收益优先用 `ai_*` |
| 错题本 ErrorsView | `/butler/error-diagnosis/{id}` + `/error-records/*` | 详情页错因卡改 AI 诊断；热力图/变式对接 |
| 学情报告 ReportView | `/butler/weekly-report` + `/report/*` | 顶部「小婷的周报」+ 各卡片 `narrative`/`ai_reason` |
| 知识图谱 GraphView | `/butler/path-plan` + `/knowledge-graph/*` | 节点学习卡 + 学习路径 |
| 对话页 DialogView | `/agent/chat` + `/butler/actions` | 保留原有交互，新增功能跳转（`build_route` 指令）+ 学情查询 |
| 模拟考试 ExamView | `/student/exam/*` | 已存在，前端补套卷列表/开始/判分/错题入本 |

## 五、降级策略（前端必须实现）

| 场景 | 处理 |
|------|------|
| AI 接口超时/异常 | 后端已回退规则模板（`copy_polish` / `butler.llm` 10s 超时 + fallback），前端无需特殊处理，字段始终有值 |
| AI 字段缺失（`ai_title` 等） | 前端回退原 `title`/`why`/`benefit` 字段 |
| 管家接口整体不可用（500） | 前端降级为静态兜底 + 骨架屏，页面不白屏 |
| 加载态 | 所有 AI 生成内容（周报/诊断/路径）加骨架屏 + `loading` 态 |
