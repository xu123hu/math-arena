# 智学数研 · AI 管家化重构总方案 v3.0

> **日期**：2026-08-14
> **类型**：顶层重构方案 / PRD + 架构 + 技术选型 + 路线图
> **参与成员**：方向明（主理人/产品舵手）、竞析（GitHub 标杆调研）、数析（代码审计综合）、瑞思（学生用户需求综合）、析客（结构化方案）、路径（路线图规划）
> **死线对齐**：8.20 功能冻结 / 9.15 比赛提交（XH-202620 科大讯飞）

---

## 📌 TL;DR（执行摘要，3-5 行）

- **核心目标**：在已有 "Agent Kernel + 6 个 Skill + FSRS-4.5 + 学情画像卡 P0 + 平台地图 P9" 的成熟 AI 基础设施上，**补齐"管家调度层 + 事件驱动 + 主动推送"**，把 AI 从"对话里的应答者"升级为"全域学习的管家"——让 AI 真正掌管推荐、诊断、规划、提醒、交互，所有卡片/建议/任务/文案均基于学生真实学情动态生成。
- **关键决策**：① 不重建 AI 内核（kernel 已是 production grade），**在现有 kernel/services 上叠加 Butler Orchestrator 调度层**；② 借鉴 LangGraph 状态机编排 + Dify 事件总线 + open-spaced-repetition/py-fsrs v5 + iflytek/astron-agent 架构；③ `growth_llm_polish` 永久开启 + today-3 / report_highlights / weak-points 从规则升级为 LLM 生成；④ 前端 7 项 `unconfigured` 全部启用 + 新增"管家视图"右栏 + 主动推送卡片。
- **预期影响**：告别"静态功能堆砌"叙事，评委第一眼看到"AI 是大脑"。复用率达 70%+（kernel/services 全保留），重构集中在 Butler 调度 worker + 前端 UI + 关键开关翻转为 ON。
- **下一步**：竞析/数析/瑞思三方报告回填 → 析客细化 PRD → 路径排 M3-M4 时间线 → 实施 → 8.20 验收。

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| **推荐方案** | 在现有"一个内核 + 三条增量路径"上叠加「AI 管家调度层（Butler Orchestrator）」，不动 kernel 与 6 个 skill 的实现 |
| **优先级** | **P0**（核心重构，决定 8.20 演示叙事能否拿下"创意实用度 20 分 + 技术先进性 10 分"） |
| **预期影响** | 评委第一眼看到"AI 是大脑"——告别"静态功能堆砌"叙事；agent_runs/event 复用 + 推荐文案点击率 ↑ + 演示动线闭环 |
| **资源需求** | 1 后端（Butler 调度 worker + 关键开关）+ 1 前端（启用 7 项 unconfigured + 新增管家视图）+ 0.5 AI（LLM 文案 prompt 微调） |
| **风险等级** | **中**（已有 AI 基础设施扎实；重构主要在 Butler 调度层 + 前端 UI + 关键开关翻转） |

---

## 1. 现状审计结论

> **关键发现**：AI 基础设施远比文档丰富，**重构不是从零造，而是"打通到前端 + 补齐主动调度层 + 翻转关键开关"**。

### 1.1 现有能力清单（按模块，标注成熟度）

#### P0 已成熟（可立即复用为"管家"底座）

| 模块 | 路径 | 成熟度 | 现状 |
|------|------|--------|------|
| **意图路由** | `app/kernel/router.py` | P0 | 三路信号 L0（slash + 承接词 + 数学结构字符）/ L2（Function Calling + L2b 纯文本兜底）/ L3（置信度闸门 ≥0.75/0.4/0.4）。**已有 emotion 双判**（挫败/焦虑/厌倦/低落/喜悦）+ shadow eval 影子评测（fire-and-forget，wf_intent_router 旁路打分落 router_eval_logs） |
| **上下文装配** | `app/kernel/context.py` | P0 | 13K token 总预算；**P0 系统人格 / P0 学情画像卡（400）/ P1 用户消息 / P2 skill 参数 / P3 RAG / P4 工作记忆 / P5 用户档案 / P6 情景记忆（800）/ P7 输出规范 / P9 平台地图（500）**；裁剪顺序 P3→P5→P4→P6（保命段永不裁） |
| **学情画像卡（AI 管家核心）** | `app/services/learning_profile.py` | P0 | `LearningProfileService` 聚合 mastery/error/streak/profile → 注入 system prompt。**注释明确写"AI 管家核心"**。60s Redis 缓存，400 token 预算，domain 隔离（MATH-/MX/BK 前缀），异常降级 None 永不抛 |
| **平台地图（AI 全局知晓平台）** | `app/services/platform_context.py` | P0 | ROLE 枚举 + `_PLATFORM_MAP` 静态常量（21 项 page/skill/unconfigured）；`match_platform_item` 本地意图拦截（动作词+功能名双条件防误触发）；`match_practice_intent` 练题中心强意图（"做套卷/练薄弱"→ 跳转 practice-lab）；对齐前端 `config/features.js` |
| **工作记忆** | `app/kernel/memory.py` | P0 | 滚动摘要（每 8 条触发 + 30min 长间隔保底）+ 最近 12 条消息 + **P6 情景记忆**（weak_kp/preference/goal/note 四类，30 天窗口，向量 cosine top3，降级 kind 优先级+最近时间）。LLM 提取 prompt 严格过滤（忽略闲聊/隐私/AI 自证/角色注入/数学范围限高中课标） |
| **防幻觉** | `app/kernel/guard.py` | P0 | 注入检测 14 条 regex + 敏感词（赌博/色情/毒品/暴力恐怖）+ 输入长度截断 4000 + 输出校验（citation/越权字段） |
| **错题本 + FSRS-4.5** | `app/services/fsrs.py` + `app/services/growth.py` | P0 | R(t)=(1+t/9S)^-1 遗忘曲线，5 级热力图 lv4→decay；m2_011_fsrs_write_path 已接入；error_records 有 fsrs_stability/fsrs_wrong_count 缓存列 |
| **错因分类（12 子类）** | `app/services/growth.py` | P0 | 五类权威（concept/formula/calculation/logic/reading）× 12 子类（concept_def/formula_confused/calc_arithmetic/logic_jump/reading_deviation/strategy_method 等）= Eedi 本土化映射 |
| **学情聚合** | `app/services/growth.py` | P0 | 综合分公式 `100*(0.6*mastery + 0.25*independence + 0.15*streak)`；hint_dependency 计算；daily_mastery_avg 趋势；12 类错因细分；`event_count` 行为埋点 |
| **引导式解题（灵魂功能）** | `app/skills/socratic_solver/main.py` | P0 | solver-then-guide 三段式（draft 题库命中 → solver 两次独立+ self-consistency + TIR SymPy 回填 → verify 沙箱步骤级复算 → guide 四级提示 Point→Teach→Bottom-out）。**find_leak 滑窗防泄题** + 情绪安抚（连续答错 ≥2 次注入降负）+ tutor_sessions.plan 隐藏底稿 + SSE 流式逐句下发 |
| **智能出题** | `app/skills/smart_quiz/main.py` | P0 | 题库检索优先 → 星火生成 → **三闸**（字段闸 4 选项/选项去重 + self_check 五检答案代回/计算复核/无歧义/难度匹配/课标内 + 格式闸 `$` 公式配对 sympify 校验）。PATCH-09 v1.9 增加"解析干净化红线"+"答案一致性红线" |
| **RAG 三路召回** | `app/kernel/rag.py` + `app/providers/embedding.py` + `app/providers/reranker.py` | P0（待 v2.2 勘误补齐）| BGE-M3 1024 维 + bge-reranker；**v2.2 勘误指出 RAG 实际退化两路召回**（7.29-7.31 部署补齐） |
| **双模型降级** | `app/providers/router.py` | P0 | 星火主 + DeepSeek-v4-flash 兜底；熔断器（10min 内 ≥2 失败熔断 5min）；流式降级纪律（已输出 token 不重流）；**管理后台配置即时生效**（三层回退：用户配置 > system_configs["model.global"] > env） |
| **题库 + 知识库** | `app/skills/question_supply.py` + `app/providers/cloud_kb.py` | P0 | GAOKAO-Bench 844 题 + chunks；必修一/二已入库；题库标签 65%→90% 冲刺中 |
| **班级 + 教师任务 + 通知** | `app/domains/classroom/` + `app/domains/coursework/` | P0 | 班级码三路径 + 教师确认闸 + assignment 状态机（草稿→发布→批改→归档）+ submission 八态 + 通知中心 |
| **动态几何** | `app/kernel/graph_block.py` | P0 | 信封协议 `graph` block（engine: jsxgraph，schema 白名单）；8 类高中高频图形 |
| **前端对话 + 信封渲染** | `frontend/src/components/chat/` | P0 | MessageBubble / IncrementalMarkdown / SocraticCompleteCard / QuizSetCard / MasteryPanel / GraphBlock / VoiceInputButton；mock/data.js 661 行演示数据 |

#### P1 已有骨架，需补全

| 模块 | 路径 | 现状 | 缺口 |
|------|------|------|------|
| **24 个学情聚合端点** | `app/gateway/growth_router.py` | overview/panel/route-intent/loop-progress/group-recommend/difficulty-mix/smart-score/summary/memory-heatmap/due-queue/detail/filter/highlights/weak-points/mastery-trend-forecast/error-distribution/honesty/knowledge-graph-{pie,tree,deps,recommend}/today-3/score-trend/feature-entries | **LLM 文案生成默认关闭**（`settings.growth_llm_polish` 默认 False → 模板原样返回）；today-3/highlights/weak-points 是规则生成不是 LLM |
| **学生端 REST** | `app/gateway/student_router.py` | error-records（CRUD + review-plan + review）/warnings/practice/streak/mastery/knowledge-graph/daily-plan/assignments | 大部分规则驱动，AI 解读缺 |
| **前端核心闭环** | `frontend/src/pages/student/` | DialogView / PracticeView / ExamView / ClassView / DualView / ErrorsView / GraphView / OverviewView / ReportView / TasksView / ProfileView | **7 项 unconfigured**：语音/可视化/推导/回溯/资源推荐/每日任务/游客演示 |
| **RAG 联网搜索** | `app/gateway/search_router.py` | **v2.2 勘误：未实现**（仅 Manifest 占位） | 8.5-8.6 补建：星辰控制台拖拽+本地接线 |

#### P2 未建（AI 管家化重构要新增）

| 模块 | 责任 |
|------|------|
| **Butler Orchestrator（管家调度层）** | 监听 LearningEvent → 决策 → 触发 LLM 生成 → 推送前端（新增） |
| **LearningEventBus（学习事件总线）** | 跨模块事件传递（错题收录/掌握度变化/打卡/视频看完/批改发回 → 触发管家思考） |
| **ButlerAction Queue（管家动作队列）** | 动作持久化 + 重试 + 幂等 + 推送（SSE/通知中心） |
| **前端"管家视图"** | 右栏"管家面板"+ 主动推送卡片 + 每日任务卡 + AI 评语卡 |
| **路径规划 worker** | 基于 mastery + goal + time + 图谱前置依赖 → 阶梯路径 |

### 1.2 核心痛点诊断（"为什么现在没有 AI 管家感觉"）

| 痛点 | 证据 | 根因 |
|------|------|------|
| **架构缺中枢** | 没有 Butler Orchestrator；`workers/__init__.py` 仅 3 行注释（"FastAPI BackgroundTasks 实现，M1 不上 Celery"），**无任何定时调度器/事件总线**——异步任务全靠请求内 BackgroundTasks，无人"主动"做事 | 架构设计上"AI 是对话应答者"假设，"AI 是大脑"的角色未落地 |
| **AI 只在对话里** | 6 个 skill 全是 chat 内触发；24 个聚合端点是数据驱动不是 AI 驱动 | skill 注册表机制没有"主动调度"模式 |
| **推荐/路径/提醒仍是静态规则** | ① features.js 7 项 `unconfigured` 占位；② growth.py today-3 规则生成；③ **`student_router.py:820` 每日一题 `daily_kp = kp_pool[date.today().toordinal() % len(kp_pool)]` —— 按"日期取模"轮换知识点，全站所有学生当天做同一知识点，与个人学情完全无关**（最强"静态推荐"证据）；④ `GROWTH_LLM_POLISH` 默认 OFF | 关键开关默认关闭 + 推荐算法写死为"日期轮换"而非"学情驱动" |
| **前端"管家"产品形态缺位** | 没有"管家视图"；没有 AI 主动推送；mock/data.js 661 行静态演示；config/features.js 中每日任务/资源推荐/可视化等写"尚未上线"/"规划在 M6" | 前端只做了"对话为主+右栏 L2 面板"，缺少"管家作为 UI 实体" |
| **学情数据丰富但解读缺 AI** | mastery/error/streak/profile/snapshot/tutor_session 全有；report_highlights/weak-points/error-distribution 返回的是数字不是"小婷的话" | `_polish_copy` 已实现但默认 OFF；模板原样返回 |
| **场景页面技能未对齐** | 双师课堂（course_companion）、错题归因（error_analysis）、批改（grading_assist）三个核心 skill 在 docs 中规划但**未在 `register_builtin_skills` 中注册**（skills/registry.py 只有 4 个：chat/qa_rag/socratic_solver/smart_quiz） | 计划漏注册到运行时 |

### 1.3 保留 vs 重构清单

#### ✅ 明确保留（不动一行代码）
- `app/kernel/router.py` 意图路由
- `app/kernel/context.py` 上下文装配（P0~P9 架构完美）
- `app/kernel/memory.py` 工作记忆 + 情景记忆
- `app/services/learning_profile.py` 学情画像卡（注释"AI 管家核心"）
- `app/services/platform_context.py` 平台地图 P9
- `app/services/fsrs.py` + `app/services/growth.py`（FSRS + 12 子类错因 + 综合分公式）
- `app/skills/socratic_solver/main.py` + `app/skills/smart_quiz/main.py`（灵魂功能）
- `app/providers/router.py`（双模型降级 + 熔断）
- `app/domains/classroom/` + `app/domains/coursework/` 业务域
- 现有 30+ 数据模型（含 mastery_records/error_records/episodic_memories/tutor_session/streaks/mastery_snapshot）
- 前端 `components/chat/*` 信封渲染 + mock/data.js 演示数据

#### 🔄 明确重构（增量不伤筋动骨）
- `settings.growth_llm_polish` 默认 OFF → **永久 ON**（关键开关翻转）
- today-3 / daily-plan / highlights / weak-points / mastery-trend-forecast：**规则 → LLM 生成**
- 前端 features.js 7 项 `unconfigured`：**全部启用**（后端接口大多已存在）
- 前端新增"管家视图"右栏 + 主动推送卡片（复用现有 MasteryPanel/GraphBlock/MessageBubble）
- smart_quiz 出题参数化：**学情驱动默认参数**（薄弱知识点+中等难度+5 道）
- 错题本反馈：**FSRS 到期 → AI 主动推送"该复习 X 了"**
- 学情报告：**数字聚合 → "小婷的周报"**（AI 解读+鼓励语）

#### ➕ 明确新增（核心重构）
- **`app/butler/`**（新目录）：Butler Orchestrator + LearningEventBus + ButlerAction Queue
- **3 张新表**：butler_events / butler_actions / ai_recommendations
- **6 个新 skill**：butler_summarize / butler_recommend / butler_path_plan / butler_notify / butler_report / butler_empathize
- **`frontend/src/views/ButlerView.vue`**（新页面）：管家主面板
- **`frontend/src/components/butler/*`**（新组件）：主动推送卡片/每日任务卡/AI 评语卡/路径推荐卡

### 1.4 缺口清单（"我们有什么" → "AI 管家需要什么"）

| AI 管家需求 | 现有 | 缺口 | 桥接路径 |
|------|------|------|------|
| 主动推送"该复习 X 了" | error_records + FSRS | 缺事件触发 + 推送通道 | butler_events.on_error_due → butler_notify skill → 通知中心/SSE |
| 每日 3 件事（AI 生成版） | today-3（规则） | 缺 LLM 编排 + 文案 | 规则数据 → butler_summarize skill → LLM 文案润色（GROWTH_LLM_POLISH ON） |
| 学情报告"小婷的话" | report/highlights（数字） | 缺 AI 解读 | 数字 + learning_profile → butler_report skill → 一段 100 字中文 |
| 资源推荐 | features.js F16 `unconfigured` | 缺整个链路 | 薄弱知识点 + 平台托管课程库 → butler_recommend skill |
| 学习路径规划 | features.js F8 `unconfigured` | 缺 worker | mastery + 图谱 deps + goal → butler_path_plan skill（结合 LangGraph 状态机） |
| 情绪安抚主动触发 | precheck emotion + chat skill | 缺跨会话触发 | 学习事件 → butler_empathize skill（如连续 3 道错题主动"休息一下"） |
| 跨会话记住偏好 | episodic_memory（4 类） | 缺"管家会利用" | P6 注入已是自动，缺"管家侧主动调度"（但learner_progress 已落库） |
| 错因自动归因 | 5 类 + 12 子类（规则+LLM） | 缺"主动给老师班级的洞察" | 错题批次 → butler_summarize → 班级周报推送教师端 |

---

## 2. 总体架构设计

### 2.1 核心命题：在不动现有"一个内核"的前提下叠加"AI 管家调度层"

```
┌───────────────────────── 接入层 ─────────────────────────┐
│ Web (Vue3 SPA) / 微信小程序（二期）/ 星辰发布渠道          │
└─────────────────────────┬─────────────────────────────────┘
                          │ HTTPS·JWT │ SSE
┌─────────────────────────▼─────────────────────────────────┐
│              智能体网关 (FastAPI)                            │
│  认证鉴权 (JWT+RBAC) · 限流 · 审计 · 路由分发              │
└────┬───────────────────────────────────┬─────────────────┘
     │ ①对话请求 (chat/socratic/quiz)    │ ②业务事件 (CRUD + Butler 触发)
┌────▼──────────────────────────┐  ┌─────▼──────────────────────┐
│  ★ Agent Kernel（不变）        │  │  ★ Butler Orchestrator（新增）│
│  router/memory/context/rag/    │  │  event_bus.subscribe()       │
│  guard · Skill 调度            │  │  butler_summarize/recommend/ │
│  (P0~P9 注入)                 │  │  path_plan/notify/report/    │
│                               │  │  empathize                   │
└──────────────┬────────────────┘  └──────────┬─────────────────┘
               │                              │
┌──────────────▼──────────────────────────────▼─────────────┐
│                  ★ 五件套（不变+增强）                       │
│  ★ Skill 层（已有 6 个 + 新增 6 个 Butler skill）           │
│  ★ 模型层（星火+DeepSeek 双通道，熔断）                     │
│  ★ 沙箱（SymPy）等价判定+验题                              │
│  ★ 数据底座（PostgreSQL+pgvector / Redis 7）                │
│  ★ 业务五域（classroom/coursework/courses/org/ops）          │
│  ★ ★ services（fsrs/growth/learning_profile/platform_ctx）  │
└────────────────────────────────────────────────────────────┘
```

### 2.2 Butler Orchestrator（管家调度层）设计

#### 职责
- **监听**：订阅 LearningEventBus 上的事件（错题收录/掌握度变化/打卡/视频看完/批改发回/情绪触发）
- **决策**：决定是否触发 Butler skill、何时触发、推送频次（防骚扰）
- **生成**：调用 LLM 生成文案/推荐/路径（**GROWTH_LLM_POLISH ON** + 6 个 Butler skill）
- **执行**：写 butler_actions 表 + 通过 SSE/通知中心推送前端
- **降级**：任何异常吞掉记日志，绝不阻塞主对话链路（同 learning_profile 设计纪律）

#### 事件订阅矩阵

| 事件源 | 事件 | 触发 Butler skill | 推送形式 |
|--------|------|------------------|----------|
| 错题收录（自动/手动）| `error_recorded` | butler_summarize（推送"为什么错"+ 变式推荐） | L1 卡片 |
| 错题复习完成 | `error_reviewed` | butler_empathize（FSRS 推进反馈） | 静默更新掌握度 |
| FSRS 到期 | `error_due` | butler_notify（"该复习 X 了"） | 通知中心+首页任务区 |
| 掌握度变化 | `mastery_changed` | butler_summarize（"X 知识点变绿了！"） | L1 卡片 |
| 打卡 | `streak_updated` | butler_empathize（连击鼓励） | 静默更新 |
| 视频看完 | `video_completed` | butler_summarize（自动生成小结卡） | L1 卡片 |
| 批改发回 | `assignment_graded` | butler_summarize（"这次失分点"+ 推荐变式） | L1 卡片 |
| 测验成绩 sudden drop | `score_dropped` | butler_empathize（情绪安抚 + 主动问"最近怎么样？"） | SSE 主动推送 |
| 情绪触发（连续挫败）| `emotion_negative` | butler_empathize（学习后 chat skill emotion 已识别） | 静默给提示 |
| 路径到期 | `path_due` | butler_path_plan（生成新阶段路径） | 首页任务区 |

#### 反骚扰规则（主动 vs 被动边界）
- **每日主动推送上限**：3 条/天（today-3 + 1 复习提醒 + 1 鼓励）
- **同一事件不重复推送**：8h 内同类事件只推一次（butler_actions 去重）
- **情绪安抚只在 chat 内**：butler_empathize 不主动推送，只在下次对话注入 system prompt
- **考试模式锁定**：学生考场模式（ai_mode=locked）下管家全部静默
- **教师可关**：教师可为本班一键关闭"管家主动推送"（保留 chat 内的引导）

### 2.3 数据流图（关键路径）

#### 路径 1：管家主动推送"该复习 X 了"
```
FSRS scheduler (每日 8:00 APScheduler)
   ↓ 扫描 error_records 找 next_review_at ≤ now
butler_events.emit('error_due', {user_id, error_record_id, kp_code})
   ↓
Butler Orchestrator: butler_actions.check_dedup(user_id, event_type, 8h)
   ↓ 首次触发
Butler Orchestrator: butler_notify.run(params, ctx)
   ↓
LearningProfileService.build_profile_card_text() → P0 注入
LLM: "你昨天在'导数应用'错过一道题，FSRS 算下来今天到期，
       要不要用 5 分钟快速复习？我可以给你出一道变式。"
   ↓
butler_actions.insert({kind: 'notify_review', payload: {...}})
   ↓
SSE push → 前端首页任务区显示"今日复习 1 题"
通知中心（小程序订阅消息）→ 学生手机
```

#### 路径 2：AI 解读"小婷的周报"
```
周日 22:00 APScheduler
   ↓ 扫描 UserDailyStat / MasterySnapshot（近 7 天）
butler_events.emit('weekly_summary_due', {user_id, week_no})
   ↓
Butler Orchestrator: butler_report.run(params, ctx)
   ↓
聚合：本周答题数/正确率/掌握度变化/薄弱点 Top3/错因分布/FSRS 进度
   ↓
P0 学习画像卡 + P4 工作记忆 + 数据
   ↓
LLM: "本周你一共做了 120 道题，正确率 78%（+3%），掌握度均值 65%。
       '导数应用'从 45% 涨到 62%，'立体几何'仍是你的薄弱点（38%）。
       建议下周专攻立体几何，每天 5 道题，3 天后我们再看看。"
   ↓ 限 150 字 + 数据校验（不得编造数字）
butler_actions.insert({kind: 'weekly_report', payload: {text, data}})
   ↓
前端"学情报告"页面 L1 卡片 / SSE 推送
```

#### 路径 3：AI 动态任务"今日 3 件事"
```
每日 7:30 APScheduler
   ↓ 扫描 mastery_records + error_records + streak
butler_events.emit('daily_plan_due', {user_id})
   ↓
Butler Orchestrator: butler_path_plan.run() → 选 3 件事
   ↓
规则骨架：
   ① FSRS 到期错题 N 道 → "今日复习 X 题"
   ② 薄弱知识点 Top1 → "专练 Y 5 题"
   ③ 连续打卡维持 → "今日一题（保持 streak）"
   ↓
LLM 文案润色（GROWTH_LLM_POLISH ON）：
   "今日复习：导数应用 2 道（FSRS 提示你今天该复习了）；
    薄弱专练：立体几何 5 道（你的掌握度 38%）；
    每日一题：解析几何综合（保持 5 天 streak！）"
   ↓
前端首页任务区三卡
```

---

## 3. 技术选型依据（每个模块借鉴开源项目）

### 3.1 借鉴矩阵

| 我们要造什么 | 借鉴开源项目 | 为什么选 | 怎么落地 |
|------|------|------|------|
| **Butler Orchestrator 状态机编排** | **LangGraph** (`langchain-ai/langgraph`, MIT, ~35k stars) | 图抽象（节点+边+共享状态）+ 持久化执行 + Human-in-loop + 已被 Klarna/Uber/LinkedIn/JPMorgan 生产验证 | Butler Orchestrator 内核用 LangGraph 思想（不引入依赖，参考其设计）；事件驱动对应"条件边"，Butler skill 对应"节点"，butler_actions 表对应"checkpoint 持久化" |
| **学习事件总线** | **Dify** (`langgenius/dify`, Apache-2.0, 151k stars) | 5 类 app 类型（Chatbot/Agent/Text Generator/Workflow/Chatflow）+ 事件驱动 + RAG pipeline + 模型网关统一 | 在 backend 加 `app/butler/event_bus.py`（轻量 pub/sub）+ Worker 进程消费；前端通过 SSE 订阅推送 |
| **FSRS v5 调度** | **open-spaced-repetition/py-fsrs** (MIT, 464 stars) + **fsrs-rs** (BSD-3-Clause, 404 stars) | 21 参数模型（我们现有 17 参数简化版是 Subset）+ DSR 模型（Difficulty/Stability/Retrievability）+ Anki 23.10+ 官方采纳 | **升级 fsrs.py** → 完整 21 参数；write_path 已就绪；read path 增加 `fsrs_optimizer.py`（训练用现有 review 数据）；新增 BUTLER 触发"error_due" |
| **错题本 + 间隔重复** | **anki-rs** / **anki source** (`ankitects/anki`, AGPL/MIT 混合) | Python+Rust 双语 + SM-2+FSRS 双算法 + 跨平台 + 数百万用户验证 | 我们的实现已经高度对齐（next_review_at / review_count / fsrs_stability）；新增"review 后即时更新 R 值"写入缓存列 |
| **AI 管家 UI 形态** | **Lobe Chat** (`lobehub/lobe-chat`, MIT, ~49k stars) + **Claude Artifacts** 模式 | TypeScript + 多模型供应商 + 插件系统 + Agent Market + 支持 server db mode + PWA + 多用户管理 | 前端右栏"管家面板"复用 Lobe Chat 的 "Plugin/Agent/Conversation" 三栏布局思路；"管家推送卡片"复用 Artifacts 的侧栏嵌入模式 |
| **教育垂类 AI 管家** | **Khanmigo**（Khan Academy，非开源但有公开 prompt） | "Deep learning, no answers"（永不直接给答案）+ 多 persona + 与内容深度绑定 + 教师+家长双视图 | 我们的 socratic_solver 已实现"永不直接给答案"+ "直接回答"二次确认；新增：管家人格统一"小婷"（已有 mock 人格），教师端"AI 控制台"（已有 `_polish_copy` 类开关） |
| **错因分类体系** | **Eedi Misconceptions**（公开数据集与论文）+ **MAP 程序性/概念性错误分类**（学术） | 学术支撑 + 业界共识 + 本土化映射（我们的 12 子类已是 Eedi 本土化版） | 维持现状；新增：`error_type` 增加"逻辑性错误 → 5 子类"细分（logic_jump/logic_hidden/strategy_method/strategy_step/...） |
| **数学解题 + 验证** | **MathBridge**（arXiv:2408.07081，英语 T5-large 738M sacreBLEU 46.8） + **ToRA**（MATH 50.8% vs 无工具 25-35%） | 中文场景不直接适用（已裁决，34 天表 §9）→ 用"讯飞 ASR + 星火 prompt 转换"；ToRA 工具增强 50%+ | 维持；新增：butler_summarize skill 调用 socratic_solver 的 `tutor_sessions.plan` 作为上下文，生成"为什么这题我引导你会卡在这一步"的解释 |
| **知识追踪（DKT/BKT）** | **chrispiech/DeepKnowledgeTracing**（DKT 论文实现，306 stars）+ **MrMaks/knowledge-tracing-collection-pytorch** | LSTM/RNN KT 模型 + ASSISTments 数据集 AUC 0.82+ + 多种变体（DKT/DKVMN/SAKT/GKT） | 维持 mastery_records 简化 BKT；**二期评估** DKT 微服务（不上 8.20 主线，避免新增基础设施）；butler 标注"哪些知识点用 DKT 预测 R 值"为 PoC 插槽 |
| **底层 Agent 平台** | **iflytek/astron-agent**（Apache-2.0, 8.6k stars, Java） | **同一生态**——我们比赛平台（讯飞星辰）+ 同一开源版本 + 工作流引擎 + MCP 工具集成 + Casdoor 认证 | 我们的解决方案已经在用星辰工作流（8 个工作流已在 34 天表规划）；新增：**butler 工作流**作为第 9 个工作流（"AI 管家编排工作流"），串联所有 Butler skill |
| **Agent 框架通用** | **OpenAI Agents SDK**（Python, MIT, ~20k stars） + **CrewAI** + **AutoGen** | Manager-Worker 模式 + Handoff + MCP 原生 | 借鉴 OpenAI Agents SDK 的"Manager + Worker + Handoff"模式做 Butler Orchestrator 内部调度；不引入依赖，直接用 Python asyncio |

### 3.2 关键技术决策

| 决策 | 选 | 不选 | 理由 |
|------|----|----|------|
| 编排框架 | **自研轻量图抽象**（借鉴 LangGraph 思想）| LangGraph（Python 依赖重）/ Dify workflow（已有星辰工作流）| 现有 kernel 已是 production grade；引入新框架风险大；自研借鉴思想更可控 |
| 事件总线 | **PostgreSQL LISTEN/NOTIFY + Redis pub/sub** | Kafka（重）/ RabbitMQ（运维复杂）| 与现有底座一致；触发频率低（每日 <100 事件/生）；失败可重试 |
| 推送通道 | **现有 SSE + 通知中心** | WebSocket / Push（小程序订阅消息二期）| SSE 已通 chat；通知中心已通教师任务 |
| 任务调度 | **现有 APScheduler** | Celery（重）/ Cron（缺监控）| 已有 workers/；事件少；可观测 |
| AI 文案生成 | **现有 ModelRouter（星火主+DeepSeek 备）** | 单独模型 / 第三方 API | 统一配额管理 + 熔断降级 |
| LLM 调用开关 | **`settings.growth_llm_polish = True` 永久开启** + 新增 `butler_llm_enabled = True` | 默认 OFF（现状）| ON 才能体现"AI 管家"；任何异常回退模板（已有 _polish_copy 的 10s 超时纪律） |
| 数据飞轮 | **现有 ai_calls 表 + 新增 butler_actions** | 新增 eval 平台 | 成本看板已有（providers/audit.py log_ai_call） |
| 路径规划 worker | **butler_path_plan skill（自研）+ 图谱 deps API** | DKT 微服务（PoC 插槽）| 图谱 deps + mastery + goal + time 已是规则骨架；LLM 编排提质量 |

---

## 4. AI 管家核心能力清单

> 对应"第三章 AI 管家核心能力"5 项。每项含**触发场景 + 产出 + 数据来源 + AI 生成点 + 与现有系统的桥接**。

### 4.1 全域学情感知

- **触发场景**：管家任何动作（推送/推荐/规划/主动对话）都需要先感知学生状态
- **产出**：学情画像卡（结构化文本）+ 实时掌握度 + 跨会话记忆
- **数据来源**：`app/services/learning_profile.py`（已有，P0 注入 system prompt）+ `app/kernel/memory.py`（P6 episodic_memories 已有，4 类 30 天窗口）
- **AI 生成点**：P0 画像卡已是 AI 管家全局知晓学生的方式，**只需保证注入稳定 + 缓存失效及时**（已有 60s Redis 缓存 + invalidate 接口）
- **桥接**：butler 任何 skill 调用前先 `get_learning_profile_service().build_profile_card_text()` → P0 注入 → LLM 知晓学生

### 4.2 智能任务生成

- **触发场景**：每日 7:30 / 路径到期 / 用户说"今天做啥" / 进入首页新会话态
- **产出**：今日 3 件事（复习 N 题 + 专练 Y 题 + 每日一题）
- **数据来源**：FSRS 到期错题队列（error_records.next_review_at）+ 薄弱知识点 Top3（mastery_records 按 mastery 排序）+ streak 维护信号（quiz_streak.py）
- **AI 生成点**：**规则骨架 + LLM 文案**——规则选 3 件事（已有 growth.py today-3 逻辑），LLM 写鼓励语/排序/卡片标题
- **桥接**：扩展现有 `GET /api/student/growth/today-3`，新增 `butler_daily_plan` skill，LLM 调用通过 `butler_llm_enabled` 开关
- **前端呈现**：首页"今日任务"三卡（核心 5 之首）+ 完成任务打勾 + 掌握度变化即时可见（已有"完成这次专练，你的'导数应用'从黄色变绿了"游戏化闭环）

### 4.3 自然语言交互

- **触发场景**：学生说"打开 X"/"我要 Y"/"今天怎么样"/"我能做什么" 等
- **产出**：直接跳转/聊天回答/管家主动问
- **数据来源**：现有 `app/services/platform_context.py`（P9 平台地图）+ `chat` skill（emotion 双判 + ESC 三段式安抚）+ `match_platform_item` / `match_practice_intent` 意图拦截
- **AI 生成点**：管家通过 chat skill 自然语言响应 + P9 平台地图让模型知晓功能直达
- **桥接**：**已有 80%**——只需新增 `管家主动对话模式`（学生不开口时，管家问"今天做点啥？"，通过学习画像卡 + today-3 数据生成提问）
- **新增**：butler_proactive_chat skill（学习画像 + today-3 → LLM 生成主动开场白）

### 4.4 动态文案生成

- **触发场景**：任何卡片标题/鼓励语/错因分析/学情评语
- **产出**：100~150 字中文，自然亲切，有数据支撑
- **数据来源**：模板（现有 growth.py `_polish_copy` 已实现）+ 真实数据（mastery/error/streak/profile）
- **AI 生成点**：**关键开关翻转** `settings.growth_llm_polish = True`（默认 OFF → ON）+ 拓展到所有卡片
- **桥接**：`_polish_copy(template, scene)` 已有 10s 超时纪律 + 异常回退模板；新增 `butler_copy_polish.py` service 复用此能力，新增 7 个 scene：
  - `daily_plan_title`（"今日 3 件事"标题）
  - `weekly_report_summary`（"小婷的周报"）
  - `error_due_notify`（"该复习 X 了"）
  - `mastery_changed_celebrate`（"X 知识点变绿了！"）
  - `streak_encourage`（"连击 X 天！"）
  - `weak_point_introduce`（薄弱点首次识别）
  - `path_milestone_celebrate`（路径阶段完成）
- **前端呈现**：所有原来"static title"的卡片都变成"AI 评语"

### 4.5 学习路径规划

- **触发场景**：新加入班级 / 重大测验后 / 主动问"我该怎么学"
- **产出**：3-7 天学习路径（知识点序列 + 每日任务 + 资源）
- **数据来源**：
  - `knowledge_points` + `kp_edges`（图谱拓扑，已有）
  - `GET /api/student/knowledge-graph/nodes/{kp_code}/deps`（前置依赖，已有）
  - `GET /api/student/knowledge-graph/nodes/{kp_code}/recommend`（节点推荐，已有）
  - `mastery_records`（掌握度）+ `goal`（从 episodic_memories 提取的目标）
- **AI 生成点**：**规则骨架 + LLM 编排**——规则保证前置依赖正确，LLM 写"为什么这样安排"+ 个性化调整
- **桥接**：新增 `butler_path_plan` skill，输入（mastery + goal + time_budget + graph_deps），输出（path: [{day, kp_code, type, reason}]）
- **前端呈现**：独立"我的学习路径"视图（L3 页面 `/student/path`），可视化时间轴 + 任务卡 + 完成反馈

### 4.6 用户视角需求清单（来自瑞思·用户研究员）

> 每项按「触发场景 + 用户感受 + 现有差距 + 改造模块」四要素。可直接作 §4 的验收锚点。

#### P0 必须（管家基本感知）

| # | 需求 | 触发场景 | 现有差距 | 改造模块 |
|---|------|---------|---------|---------|
| P0-1 | 主动告诉我"今天该做什么" | 进平台新会话态首页 | F8 学习路径未上线，系统建议队列缺位 | F8（规则→AI 开场白）+ 首页任务区三卡 |
| P0-2 | 看学情后主动鼓励/预警 | 提交作业/做完题/周报点 | F6 是图表聚合无 AI 解读，预警只同步教师 | F6（growth 数据 → LLM 周报解读 + 学生侧温和提示） |
| P0-3 | 主动推送薄弱点复习 | FSRS 到期（1/3/7/15 天）或 mastery 变黄 | FSRS 已就绪但只作错题本页静态入口，无主动触达 | F4 复习提醒 + 通知中心/首页任务区 + 定时 worker |
| P0-4 | "我要刷题"→ AI 自动选薄弱点+难度+题量 | 学生不带参数说"给我出几道题" | F2 需手动说明参数，缺省值 M3 才做 | F2 出题缺省参数 = 学情驱动（**建议提前 M2**）+ smart_quiz mastery 查询 |

#### P1 重要（管家深度感知）

| # | 需求 | 触发场景 | 现有差距 | 改造模块 |
|---|------|---------|---------|---------|
| P1-1 | 主动识别情绪并安抚 | 连续答错/负向措辞/刷题超时 | emotion 标签已识别但只作输入信号，未触发关怀动作 | F1 情绪安抚（提前）+ 管家关怀层（降难度/鼓励/休息提醒） |
| P1-2 | 资源推荐动态化 | 暴露薄弱点后推"看课/专练/讲解"三选一 | F16 是 M6 级 50 条静态映射 | F16 静态→ mastery+偏好动态推荐 + user_profile 偏好字段 |
| P1-3 | 看课完成后 AI 总结 + 关联错题 | 看完教师布置的课，检测题有错 | F9 有阶段总结/检测，但错题闭环未强调主动 | F9 course_companion + F10 后续动作卡 |
| P1-4 | 批改发回后 AI 主动分析失分点 | 学生收到批改发回，打开成绩单 | F3 有"引导重解"按钮，缺"失分共性归纳" | F3 发回通知 → 追加 AI 失分分析卡 + grading_assist 复用 |

#### P2 加分（管家人格化）

| # | 需求 | 现有差距 | 改造模块 |
|---|------|---------|---------|
| P2-1 | AI 知道学习习惯（时段/文字或语音偏好）| user_profile 未建学习习惯维度 | user_profile M2 扩展 + 行为埋点回写 |
| P2-2 | 跨设备/跨会话记住偏好 | episodic_memories 表已设计但 M3 才建 | 记忆子系统情景记忆 + 管家"回忆"话术 |
| P2-3 | 主动设计小挑战/小测验 | F5 刷题只有被动三模式 | F5 新增"管家挑战"模式 + streak 游戏化 |

### 4.7 管家"人格"设计（来自瑞思）

- **统一人格"小婷"，不另起炉灶**：管家与小婷是同一个"小婷"，从"被动应答者"升级为"主动照护者"；对内 PRD 定位"你的数学学习管家"，答辩叙事"苏格拉底式学习伙伴 + 学习管家"双定位
- **视觉**：几何简约 icon（三角+上升曲线）蓝紫主色，**不萌系拟人**（高三生抵触卡通宠物）；主动出现用"轻敲门"式气泡，情绪关怀用柔光+一句话，预警用温和黄非红
- **主动 vs 被动边界**：主动推仅 4 类高价值低打扰场景（开场/节点/异常/到期）；学生沉浸作答中、考试模式、连续划走的同类提醒→不主动；角标仅"教师任务/批改发回/预警"三类红角标
- **四条红线**：①不能替代思考（可规划"做什么"，绝不替解"答案"）；②不给答案（泄露率=0，直接看解析走二次确认）；③不制造焦虑（"最近导数有点卡，要不要 10 分钟专练？"而非"你严重退步"）；④不逼学习/不评判人格（日刷题上限 30、45 分钟休息提示、只说题不说"你笨"）

---

## 5. 分模块改造方案

> 每个模块：**现状 → 改造后 → 数据源 → AI 生成点 → 验收**。

### 5.1 学情总览（OverviewView）

- **现状**：聚合数字（掌握度/答题数/正确率），**静态模板**文案（"本周答题 X 道"）
- **改造后**：L2 右栏"小婷的话"卡片（AI 解读 + 鼓励 + 主动推荐）+ L1 摘要卡"本周亮点"+"本周待改进"
- **数据源**：`/api/student/growth/overview`（已有）+ `/api/student/report/highlights`（已有，规则）+ 学习画像卡 P0
- **AI 生成点**：GROWTH_LLM_POLISH ON + 新增 `butler_weekly_highlight` skill
- **验收**：3 名落地学生盲评"小婷的话"自然度 ≥4/5

### 5.2 练题中心（PracticeView / DialogView 出题）

- **现状**：用户输入"出几道 X 题"→ smart_quiz 生成题组卡 → 开始自测；**每日一题 `student_router.py:820` 按 `date.toordinal() % len(kp_pool)` 日期取模选知识点，全站同题、与学情无关**
- **改造后**：
  - **每日一题学情化**：`daily_kp` 从"日期取模"改为"该生薄弱知识点 Top1 加权轮换"（读 mastery_records 薄弱 Top + 昨日已练去重）
  - **学情驱动默认参数**（薄弱知识点 + 中等难度 + 5 道）；首页任务区"今日专练"一键直达
- **数据源**：`smart_quiz` skill（已有）+ mastery_records 薄弱 Top + 学习画像卡
- **AI 生成点**：**默认参数由 LLM 根据画像卡生成**（替代写死），用户也可覆盖
- **验收**：3 名落地学生"今日专练"参与率 ≥40% DAU；每日一题与薄弱点匹配率 ≥80%

### 5.3 错题本（ErrorsView）

- **现状**：三视图（知识点/时间/错因）+ 详情页 + FSRS 间隔复习
- **改造后**：
  - L1 卡片"AI 错因解读"（自动归因后给"为什么会错"+ 知识图谱节点跳转）
  - 复习推送（FSRS 到期自动推"该复习 X 了"）
  - 变式巩固（已生成 3 道变式走 F2/F3 管线）
- **数据源**：`error_records` + `error_tags` + 12 子类错因 + FSRS + 图谱 deps
- **AI 生成点**：新增 `butler_error_interpret` skill（错因→"为什么"+"怎么避免"）
- **验收**：错因解读盲评准确度 ≥75%

### 5.4 学情报告（ReportView）

- **现状**：数字聚合 + 趋势图 + 错因分布
- **改造后**：
  - 周报："小婷的周报"（150 字 AI 解读）
  - 预测："按你的进度，3 天后导数应用会从 65% 到 75%"（mastery-trend-forecast + LLM 解读）
  - 同伴对比（匿名，默认关闭）
- **数据源**：`/api/student/report/*`（已有）+ mastery_snapshots 趋势
- **AI 生成点**：GROWTH_LLM_POLISH ON + 新增 `butler_report_narrate` skill
- **验收**：周报生成 ≤5s，盲评"可读性+激励性" ≥4/5

### 5.5 知识图谱（GraphView）

- **现状**：静态知识树 + 节点点击展开（掌握度/相关错题 3 道/挂载刷题）
- **改造后**：
  - 学习脉络（最近学习轨迹连线）—— M4 增强，已有
  - "同学们都在攻克"匿名热力—— 二期
  - **节点点击** → L2 内展开"AI 学习卡"（含节点讲解+相关错题 AI 解读+推荐路径）
- **数据源**：knowledge_points + kp_edges + mastery_records + error_records
- **AI 生成点**：新增 `butler_graph_node_card` skill（节点 → 学习卡）
- **验收**：节点学习卡加载 ≤3s

### 5.6 侧边栏（侧边导航 + 顶部头像区）

- **现状**：9 项导航 + 1 项沉浸式（前端 nav.js）+ features.js 核心 5+实验室 7（7 项 unconfigured）
- **改造后**：
  - **核心 5 不变**：对话学习 / 练题中心 / 错题本 / 学情报告 / 个人中心
  - **实验室 7 全部启用**：
    - 语音讲解 F12 → M3 TTS（接讯飞 TTS）
    - 可视化讲解 F13 → M6 讲题卡片动画（已规划）
    - 推导检查 F14 → M4+ 试点（科研端验证中台复用）
    - 课堂回溯 F15 → M6 demo
    - **资源推荐 F16 → 启用**（butler_recommend skill）
    - **每日任务 F8 → 启用**（butler_path_plan skill，今天的核心）
    - **游客演示 F17 → M4 启用**（已有 /demo 路由思路）
  - **新增"管家视图"**：右栏"管家面板"+ 主动推送卡片（复用现有 toast 通道）
  - **角标克制**：只有"教师任务/批改发回/管家提醒"三类允许红色角标
- **数据源**：现有 `config/features.js` + `nav.js` + 后端 services
- **AI 生成点**：所有 7 项 unconfigured 启用 + 新增"管家面板"
- **验收**：7 项 unconfigured 全部有可用入口；管家面板在首页可见

---

## 6. 数据库改造方案

### 6.1 新增表（Alembic 迁移随 butler 模块入库）

#### `butler_events`（学习事件总线持久化）
```sql
CREATE TABLE butler_events (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    event_type VARCHAR(64) NOT NULL,  -- error_recorded/error_due/mastery_changed/...
    source_type VARCHAR(32) NOT NULL,   -- error_record/submission/streak/watch_event...
    source_id UUID,                     -- 源记录 id（软引用，无 FK，便于跨域）
    payload JSONB NOT NULL,
    idempotency_key VARCHAR(128) UNIQUE, -- 幂等：同 source_type+source_id+event_type 去重
    status VARCHAR(16) DEFAULT 'pending',  -- pending/processing/done/failed
    retry_count INT DEFAULT 0,
    next_retry_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    INDEX (user_id, status, created_at),
    INDEX (event_type, created_at)
);
```

#### `butler_actions`（管家动作队列+幂等+重试）
```sql
CREATE TABLE butler_actions (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    event_id UUID REFERENCES butler_events(id),
    action_type VARCHAR(64) NOT NULL,  -- notify_review/daily_plan/weekly_report/...
    scene VARCHAR(32) NOT NULL,  -- daily_plan_title/error_due_notify/...
    payload JSONB NOT NULL,  -- {template, data, generated_text}
    deliver_channels TEXT[] NOT NULL DEFAULT '{}',  -- [sse, notification_center, ...]
    available_at TIMESTAMPTZ,     -- 延迟投递时间（如"次日 7:30 推"）
    delivered_at TIMESTAMPTZ,
    dedup_key VARCHAR(128),  -- 去重键 user_id+action_type+8h（部分唯一索引）
    status VARCHAR(16) DEFAULT 'pending',
    retry_count INT DEFAULT 0,
    next_retry_at TIMESTAMPTZ,
    llm_latency_ms INT,           -- LLM 生成耗时（成本看板 + 文案质量回溯）
    created_at TIMESTAMPTZ DEFAULT NOW(),
    INDEX (user_id, status, created_at),
    INDEX (action_type, created_at)
);
-- dedup_key 部分唯一索引：仅对未投递/待投递的行去重，历史行不占唯一性
CREATE UNIQUE INDEX uq_butler_actions_dedup ON butler_actions(dedup_key)
    WHERE status IN ('pending', 'available') AND dedup_key IS NOT NULL;
```

#### `ai_recommendations`（AI 推荐结果，可被学生反馈）
```sql
CREATE TABLE ai_recommendations (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    kind VARCHAR(32) NOT NULL,  -- daily_task/review_due/path_step/resource/...
    source VARCHAR(32) NOT NULL,  -- butler_path_plan/butler_recommend/butler_notify
    payload JSONB NOT NULL,  -- {items: [...], reason, ...}
    llm_prompt_hash VARCHAR(64),
    llm_model VARCHAR(64),
    user_feedback VARCHAR(16),  -- accept/reject/skip
    shown_at TIMESTAMPTZ,
    acted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    INDEX (user_id, kind, created_at)
);
```

### 6.2 扩展字段（既有模型）

| 表 | 新增字段 | 用途 |
|----|---------|------|
| `conversations` | `butler_proactive_count INT DEFAULT 0` | 跟踪管家主动推送次数（防骚扰） |
| `user_profiles` | `butler_enabled BOOLEAN DEFAULT TRUE` | 学生可关闭管家主动推送 |
| `user_profiles.preferences` (JSONB) | `butler_scenes JSONB` | 学生可配置哪些 scene 接收（如关闭"鼓励"但保留"复习提醒"） |
| `assignments` | `butler_summary_enabled BOOLEAN DEFAULT TRUE` | 教师可为本班关闭批改发回后 AI 解读 |
| `events` | `butler_triggered BOOLEAN DEFAULT FALSE` | 标记哪些 event 触发了管家（数据飞轮） |

### 6.3 索引策略

- `butler_events(user_id, status, created_at)` —— 管家 worker 查询待处理事件
- `butler_events(event_type, created_at)` —— 按类型聚合统计
- `butler_actions(dedup_key UNIQUE)` —— 8h 去重
- `butler_actions(user_id, status, created_at)` —— 推送状态查询
- `ai_recommendations(user_id, kind, created_at)` —— 推荐历史查询

---

## 7. 接口改造清单

### 7.1 复用（已有端点）

| 端点 | 用途 | Butler 复用方式 |
|------|------|----------------|
| `GET /api/student/growth/today-3` | 今日 3 件事（规则）| 升级为 LLM 润色 |
| `GET /api/student/growth/overview` | 全域学情 | 管家面板"管家的话"数据源 |
| `GET /api/student/report/highlights` | 本周亮点 | LLM 解读 |
| `GET /api/student/report/weak-points` | 薄弱 Top4 | LLM 解读 |
| `GET /api/student/report/mastery-trend-forecast` | 趋势预测 | LLM 解读 |
| `GET /api/student/error-records/due-queue` | FSRS 到期 | 管家推送"该复习 X 了"的数据源 |
| `GET /api/student/error-records/memory-heatmap` | FSRS 热力 | 管家面板显示 |
| `GET /api/student/knowledge-graph/tree` | 图谱树 | 管家推荐"薄弱节点"依赖 |
| `GET /api/student/knowledge-graph/nodes/{kp_code}/deps` | 前置依赖 | 管家路径规划 worker |
| `GET /api/student/knowledge-graph/nodes/{kp_code}/recommend` | 节点推荐 | 管家推荐系统 |

### 7.2 扩展（现有端点新增字段）

| 端点 | 新增字段 | 用途 |
|------|---------|------|
| `GET /api/student/growth/today-3` | `ai_title`, `ai_intro`, `ai_encourage` | LLM 生成的标题/介绍/鼓励语 |
| `GET /api/student/growth/overview` | `butler_message` (string), `butler_actions` (array) | 管家消息 + 待执行动作 |
| `GET /api/student/report/highlights` | `narrative` (string) | AI 解读段 |
| `POST /api/student/error-records` | `ai_interpret` (string) | 错题收录后 AI 解读 |
| `GET /api/student/assignments/{id}` | `ai_summary` (string) | 批改发回后 AI 总结 |
| `GET /api/student/warnings` | `butler_suggestion` (string) | 预警对应管家建议 |

### 7.3 新增（管家调度端点）

#### Butler 调度核心

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/butler/events/emit` | POST | 业务模块上报学习事件（如错题收录后） |
| `/api/butler/actions/poll` | GET (SSE) | 前端 SSE 订阅管家推送 |
| `/api/butler/actions/{id}/feedback` | POST | 学生反馈（接受/拒绝/跳过）→ 数据飞轮 |
| `/api/butler/dashboard` | GET | 管家面板（右栏 L2）数据 |
| `/api/butler/daily-plan` | GET | 今日 3 件事（LLM 生成版） |
| `/api/butler/weekly-report` | GET | 周报（"小婷的话"） |
| `/api/butler/path-plan` | GET/POST | 学习路径规划 |
| `/api/butler/recommend` | GET | 资源推荐 |
| `/api/butler/notify/settings` | GET/PATCH | 管家推送设置（学生可关） |
| `/api/butler/events/stats` | GET (admin) | 数据飞轮统计 |

#### Butler Skill 端点（对内）

| 端点 | 用途 |
|------|------|
| `/internal/butler/skill/summarize` | butler_summarize skill 调用 |
| `/internal/butler/skill/recommend` | butler_recommend skill 调用 |
| `/internal/butler/skill/path-plan` | butler_path_plan skill 调用 |
| `/internal/butler/skill/notify` | butler_notify skill 调用 |
| `/internal/butler/skill/report` | butler_report skill 调用 |
| `/internal/butler/skill/empathize` | butler_empathize skill 调用 |

---

## 8. 测试验证方案

### 8.1 测试路径

| 阶段 | 测试 | 工具 | 通过标准 |
|------|------|------|----------|
| **单元** | 每个 Butler skill prompt 模板 + 数据适配 | pytest + golden dataset | 模板渲染 100% 一致 |
| **集成** | 事件→技能→推送 链路 | pytest-asyncio + httpx + 临时 PostgreSQL/Redis | 事件 100% 触发对应 skill；推送 95%+ 成功；8h 去重 100% |
| **LLM 评估** | LLM 文案质量 | held-out 评测集（每周跑分）| 自然度盲评 ≥4/5；不编造数字（数字校验 100%）；prompt 注入拦截率 ≥95% |
| **端到端** | 完整闭环：错题收录 → 推送 → 学生查看 → 反馈 | Playwright + 真实后端 | 5 个核心场景全通 |
| **压测** | 50 并发学生在线（每日推送 + chat 混跑） | locust + k8s | 推送延迟 P95 ≤2s；不阻塞 chat 首字 ≤3s |
| **合规** | AI 生成内容标识 + 未成年人数据保护 | 自动化 + 人工抽查 | 标识 100%；隐私合规 100% |

### 8.2 验收标准（对齐 M2~M5 Gate）

| Gate | 新增验收项 | 标准 |
|------|----------|------|
| **M2 学生端 Gate（8.7）** | ① butler 事件→推送链路通；② 关键开关 GROWTH_LLM_POLISH 永久 ON；③ today-3 LLM 生成版上线 | 事件 100% 触发；LLM 渲染成功率 ≥95%；盲评 ≥4/5 |
| **M3 教师端 Gate（8.13）** | ④ 周报"小婷的话"上线；⑤ 批改发回 AI 总结；⑥ 教师可关闭管家推送 | 6 项全通；教师控制台有"AI 推送开关" |
| **M4 科研端 Gate（8.17）** | ⑦ 学习路径规划 LLM 版 demo；⑧ 资源推荐 demo | 路径规划 1 个学生 demo 跑通；推荐 ≤3s |
| **M5 冻结验收（8.20）** | ⑨ 演示动线：错题 → 管家推送 → 复习 → 掌握度变绿 → 周报解读 → 教师端异议；50 人试用启动 | 演示动线闭环 5 个 wow 点；50 人试用覆盖教师端 + 学生端 |

### 8.3 风险预案

| 触发 | 预案 |
|------|------|
| LLM 调用超时/失败 | `_polish_copy` 已有 10s 超时纪律 + 异常回退模板；Butler skill 同样纪律 |
| 推送被学生举报骚扰 | butler_actions.dedup_key + 每日上限 3 条 + 学生一键关闭 |
| 路径规划 LLM 给出不合理前置依赖 | 规则骨架保底（mastery + graph_deps），LLM 仅做文案/微调 |
| 事件总线 PostgreSQL NOTIFY 失败 | 降级为定时轮询（APScheduler 每 5 分钟扫 butler_events）|
| 文案"编造数据"事故 | LLM prompt 强约束"只润色不改数字" + 后处理数字校验（模板中数字 vs LLM 输出数字一致性）|

---

## 9. 创新点提炼（对应比赛要求 7 维度）

> 对齐 XH-202620《评分标准》100 分制 7 维度，重点是 **创意实用度 20 分 + 技术先进性 10 分 + 用户认可度 10 分**。

### 9.1 创意实用度（20 分）

**核心创新**：**AI 管家作为产品形态**，而非技术模块。

- 解决"AI 在哪里"问题：评委第一眼看到的就是"管家"——右栏面板+主动推送+每日任务+AI 评语，**AI 是大脑**而非"对话里的应答者"
- 解决"AI 怎么用"问题：学生不开口时管家主动；学生开口时管家听懂；学生结束时管家记住（跨会话）
- 对应赛题三场景：助学（管家主动推复习/鼓励/路径）+ 助教（教师端看见学生管家数据）+ 助研（错题/掌握度数据回流驱动教育研究）

### 9.2 技术实现度（20 分）

- **8 个现有工作流 + 1 个新增 butler 工作流**（星辰线满分）
- **Butler Orchestrator + LearningEventBus + 6 个 Butler skill**（架构加分）
- **GROWTH_LLM_POLISH 永久 ON** + 双模型降级 + 熔断 + RAG 三路 + 13K 上下文装配（技术扎实）
- **FSRS 完整 21 参数升级**（学术前沿）

### 9.3 技术先进性（10 分）

- **LangGraph 思想 + 自研图抽象**（生产级编排，可观测可恢复）
- **Dify 事件总线**（多源异步事件流）
- **Astron-agent 兼容**（同生态，与星辰工作流联动）
- **open-spaced-repetition v5 升级**（教育领域最新调度算法）

### 9.4 内容质量度（20 分）

- **AI 解读"小婷的话"**：不编造数字、有数据支撑、自然亲切（GROWTH_LLM_POLISH + 数字校验）
- **AI 错因解读**：12 子类细分 + "为什么会错 + 怎么避免"模板（Eedi 本土化）
- **AI 学习路径**：图谱 deps 规则骨架 + LLM 编排（保证前置正确 + 个性化文案）

### 9.5 商业化潜力（10 分）

- **复用率高 70%+**：kernel/services 全保留；新增 Butler 模块独立可部署
- **可推广**：高三数学 → 高一高二数学 → 物理/化学/生物（同一架构）
- **可对接**：讯飞智文 PPT、智文学习机、星辰 App/公众号

### 9.6 用户认可度（10 分）

- **50 人试用覆盖教师端 + 学生端**
- **盲评 ≥4/5**（小婷的话/错因解读/路径规划）
- **参与率指标**：今日专练参与率 ≥40% DAU；任务完成率 ≥50%
- **情绪安抚有效率**：挫败情绪 chat 反馈 ≥4/5

### 9.7 作品完成度（10 分）

- 思维导图 41 项功能全覆盖（除希沃监控）
- 三端全闭环 + Butler 调度层
- 8 个工作流 + 2 个微调模型 + Butler 工作流
- 50 人试用进行中 + 演示动线闭环

### 9.8 加分（最高 10 分）

50 人以上规模化使用 → 管家推送点击率 + 路径完成率数据 → 答辩材料

---

## ✅ 行动清单（按路径·路线图规划师重排：6 天冲刺 P0/P1/P2）

> **核心判断**：`翻转开关 + 复用现有接口` = 低成本高杠杆（半天~1天）；`新建 worker + 前端新页面` = 高成本（2天+）。**6 天窗口里 Butler 只押"一条最小闭环"，不做 6 个 skill 全量。**

### P0（8.14~8.17 必做，直接决定"AI 是大脑"叙事）

| # | 行动 | Owner | 依赖 | 验收 |
|---|------|-------|------|------|
| P0-1 | 翻转 `growth_llm_polish=True` + 部署 `_polish_copy` 全部 7 scene | 后端 | 无（`_polish_copy` 已实现）| 配置默认 ON；7 scene 单测 100%；异常回退模板 |
| P0-2 | 修每日一题静态推荐（`student_router.py:820` 日期取模→薄弱点 Top1 加权轮换）| 后端 | 无 | 每日一题与薄弱点匹配 ≥80%；半天交付 |
| P0-3 | today-3 升级 LLM 生成版（扩展现有端点 + 复用 `_polish_copy`）| 后端+AI | P0-1 | 返回 `ai_title/ai_intro/ai_encourage`；数字校验 100% |
| P0-4 | 前端 features.js 7 项 `unconfigured` 全部启用 | 前端 | 后端接口盘点 | 7 项均有入口（重点 F8 每日任务 / F16 资源推荐）|
| P0-5 | Butler 最小闭环：event_bus + butler_notify + error_due + 8h 去重 + SSE | 后端 | P0-2 | 错题→"该复习X了"→首页→复习→掌握度变绿 端到端通 |
| P0-6 | 前端 ButlerView.vue 最小版（右栏管家面板+今日任务卡，复用现有组件）| 前端 | P0-5 | 管家面板首页可见；推送卡渲染 |

### P1（8.17~8.19 尽力做，锦上添花）

| # | 行动 | Owner | 依赖 | 验收 |
|---|------|-------|------|------|
| P1-1 | 周报"小婷的话"（butler_report 复用 highlights + `_polish_copy`）| 后端+AI | P0-1 | 150 字 AI 解读 ≤5s，数字校验 |
| P1-2 | 批改发回 AI 总结 + 掌握度变化 celebrate/streak 鼓励 | 后端 | P0-5 | assignment 返回 `ai_summary` |
| P1-3 | 学生/教师可关推送（butler settings + 反骚扰上限 3 条/天）| 后端+前端 | P0-5 | 控制台有 AI 推送开关 |
| P1-4 | 资源推荐/路径规划 demo（规则骨架版，不追 LLM 全量）| 后端 | P0-2 | 1 名学生路径 demo 跑通 |

### P2（8.20 后材料期 / 二期）

- FSRS 完整 21 参数升级 + fsrs_optimizer 训练（PoC）
- 6 个 Butler skill 全量注册 + 反骚扰精细化
- 微信小程序订阅消息 / 国家智慧教育平台资源源
- DKT 微服务、50 人规模化评测集跑分

### 逐日甘特（8.14~8.20）

| 日 | 当天完成 | 验收点 |
|----|---------|--------|
| **8.14** | 后端 P0-1 开关 + P0-2 修每日一题；前端盘点 7 项接口；AI 定稿 7 scene prompt | 配置 ON；每日一题按薄弱点返回 |
| **8.15** | 后端 P0-3 today-3 LLM + 3 张表 migration；前端启用后端就绪的 3~4 项；内容建 20 条盲评样本 | today-3 返回 AI 文案 |
| **8.16** | 后端 P0-5 最小闭环；前端 P0-6 ButlerView 最小版 | 事件→skill→去重链路单测通 |
| **8.17** | SSE 端点 + APScheduler 扫 error_due；推送卡+通知中心；**决策门** | M4 科研端 Gate；Butler 闭环 demo 通 |
| **8.18** | P1-1 周报；报告页接 narrative | 周报 ≤5s |
| **8.19** | P1-2 批改总结 + celebrate；收尾 + 反骚扰开关 | 盲评 ≥4/5 |
| **8.20** | 功能冻结 + 演示动线 final walkthrough + 50 人试用启动 | M5 Gate；5 个 wow 点闭环 |

### 砍序预案（来自路径）

- **场景 A（8.17 worker 没跑通）**：砍全部依赖 worker 的主动推送（P0-5/6 的 SSE 链路）；保所有"请求内同步生成"的 AI 文案（开关 ON / today-3 LLM / 每日一题学情化 / 前端 7 项 / 周报解读）；叙事从"AI 主动推"降级为"AI 在页面/回答里是大脑"。
- **场景 B（LLM 文案超时/质量差）**：第一级 `_polish_copy` 10s 超时回退模板；第二级规则模板原样返回；**红线：数字校验后处理，宁可回模板也不编造数字**。

---

### 利益相关者沟通要点（三版本，来自路径）

**① 给技术组长（高管视角，3 句话）**
1. 三端已建好，缺的是"AI 主动掌舵"——Butler 调度层让 AI 从"对话应答者"变"全域管家"，这是评委第一眼的"AI 是大脑"叙事，对应创意实用度 20 分。
2. 不动 kernel 和 6 个 skill 一行代码，只在上面叠一个独立可部署调度层，**复用率 70%+**。
3. 关键开关 ON + 每日一题学情化 + 前端 7 项启用，全是半天~1天的高杠杆改动，8.20 前稳拿，不赌新建大模块。

**② 给前端开发（工程视角）**
- 复用现有组件（MasteryPanel / MessageBubble / IncrementalMarkdown / GraphBlock），不重写；只新增 1 个 `ButlerView.vue`，不新建路由体系；启用 7 项 unconfigured（后端接口大多已存在，重点 F8 每日任务 + F16 资源推荐）。

**③ 给内容/测试（设计视角）**
- 文案用"规则骨架给数据 + LLM 只润色不改数字"范式，统一"小婷"人格、150 字内；评测集 held-out 20~50 条盲评（自然度 ≥4/5 + 数字一致性 100% + 注入拦截 ≥95%）；5 核心场景 Playwright 全通。

---

## ⚠️ 待确认 / 假设 / Non-goals

### 待团队决策事项
1. **GROWTH_LLM_POLISH 永久开启的成本评估**：每天 50 万人每人 3 条文案 × 150 字 ≈ 需评估 token 消耗与成本
2. **butler_proactive_chat 触发时机**：是每天首次登录推一句？还是学生不操作 30 分钟后推？
3. **资源推荐 F16 的资源源**：只用平台托管课程？还是也接国家中小学智慧教育平台？
4. **每日推送上限 3 条**：是绝对上限？还是教师可调？
5. **错因解读默认 ON 还是默认 OFF**：F4 验收需要，建议默认 ON + 可关
6. **管家统一复用"小婷"人格**（来自瑞思）：是否认可管家与小婷同一人格、不新建角色？（影响人格层是否独立建模）
7. **P0-4 出题缺省参数从 M3 提前到 M2**（来自瑞思）：涉及 smart_quiz 的 mastery 查询依赖，需在 8.2~8.4 出题 slot 内提前接通学情聚合
8. **管家主动触达仅走站内**（来自瑞思）：PC Web 一期无系统级推送，主动形态限制为首页任务区/角标/对话开场，是否接受？
9. **today-3 三字段（ai_title/ai_intro/ai_encourage）单次成本**（来自析客）：三字段是一次 LLM 调用还是三次？影响 token 消耗与延迟
10. **每日一题薄弱点加权轮换的权重公式**（来自析客）：`daily_kp` 改"薄弱 Top1 加权"具体权重怎么定（mastery 越低权重越高？昨日已练降权？）
11. **事件上报时点**（来自析客）：butler_events 是业务事务内同步 emit（强一致但阻塞）还是事务后异步 emit（不阻塞但可能漏）？

### 假设
- 星火 API 配额稳定，赛事 500 元 tokens 福利+并发提升渠道够用
- 50 人试用在 8.18 前启动，能覆盖 Butler 推送场景
- 教师不会因为"管家推送"感到失控（有控制台可关）

### Non-goals（M2~M5 不做）
- ❌ DKT 微服务（PoC，二期）
- ❌ 摄像头课堂行为分析（伦理）
- ❌ 学生间社交（隐私）
- ❌ 独立家长账号（合规复杂度）
- ❌ Lean4 形式化验证（仅 M4 火种）
- ❌ WebSocket / 推送小程序订阅消息（二期）

---

## 📚 数据来源 & 成员产出索引

- **方向明（主理人/产品舵手）**：本方案主笔；先后端代码审计（kernel/services/skills/gateway/models 全量）+ 前端代码审计（config/components/pages/mock）+ GitHub 标杆 WebSearch 验证 12+ 项目 URL + 文档通读（whiteboard PDF + 6 份 MD）+ 团队 brief 编排
- **竞析（GitHub 标杆调研）**：任务执行中；已完成 LangGraph/Dify/astron-agent/py-fsrs/fsrs-rs/ts-fsrs/Lobe Chat/Anki/DKT/BKT 等方向验证（待团队报告回填细化）
- **数析（代码审计综合）**：任务执行中；已读取 kernel/services/skills/gateway 全量文件 + frontend config/components 全量文件，待输出《现状能力清单与缺口报告》最终版
- **瑞思（学生用户需求综合）**：任务执行中；已通读 17 个功能 F1-F17 + 回填问卷结论 + 思维导图，待输出《学生画像与 AI 管家需求清单》最终版
- **析客（结构化方案）**：待上游报告完成后 dispatch
- **路径（路线图规划）**：待析客完成后 dispatch

### 开源项目 URL（已验证真实存在，≥15 个）

| 项目 | URL | Star | License |
|------|-----|------|---------|
| LangGraph | https://github.com/langchain-ai/langgraph | ~35k | MIT |
| LangChain | https://github.com/langchain-ai/langchain | ~120k | MIT |
| Dify | https://github.com/langgenius/dify | 151k | Apache-2.0 (derivative) |
| iflytek/astron-agent | https://github.com/iflytek/astron-agent | 8.6k | Apache-2.0 |
| Lobe Chat | https://github.com/lobehub/lobe-chat | ~49k | MIT |
| OpenAI Agents SDK | https://github.com/openai/openai-agents-python | ~20k | MIT |
| CrewAI | https://github.com/crewAIInc/crewAI | ~20k | MIT |
| AutoGen | https://github.com/microsoft/autogen | ~40k | MIT |
| AutoGPT | https://github.com/Significant-Gravitas/AutoGPT | ~170k | MIT |
| AgentGPT | https://github.com/reworkd/AgentGPT | ~32k | GPL-3.0 |
| open-spaced-repetition/py-fsrs | https://github.com/open-spaced-repetition/py-fsrs | 464 | MIT |
| open-spaced-repetition/fsrs-rs | https://github.com/open-spaced-repetition/fsrs-rs | 404 | BSD-3-Clause |
| open-spaced-repetition/ts-fsrs | https://github.com/open-spaced-repetition/ts-fsrs | 739 | MIT |
| open-spaced-repetition/fsrs4anki | https://github.com/open-spaced-repetition/fsrs4anki | 4k | MIT |
| ankitects/anki | https://github.com/ankitects/anki | ~20k | AGPLv3/MIT |
| chrispiech/DeepKnowledgeTracing | https://github.com/chrispiech/DeepKnowledgeTracing | 306 | - |
| sulingling123/Knowledge_Tracing | https://github.com/sulingling123/Knowledge_Tracing | 76 | - |
| MrMaks/knowledge-tracing-collection-pytorch | https://github.com/MrMaks/knowledge-tracing-collection-pytorch | - | - |
| mem0ai/mem0（自适应记忆框架）| https://github.com/mem0ai/mem0 | ~30k | Apache-2.0 |
| Khanmigo (Khan Academy AI) | https://www.khanmigo.ai/ | (非开源，公开 prompt) | - |

> 竞析（竞品分析师）经 WebSearch 交叉验证了 22 个项目，上表为最核心、与「AI 管家化」直接相关的 20 个；另有 MathBridge（arXiv:2408.07081）、ToRA、Eedi misconceptions 等论文/数据集类依据在 §3.1 与正文引用。

---

> **本报告由产品战略团队 AI 协作生成（方向明主笔 + 竞析/数析/瑞思并行调研，析客/路径待补），重要决策请由产品负责人 + 技术组长审定。**
> **📄 完整报告已保存：deliverables/product-strategy/ai-butler-restructure-2026-08-14.md**