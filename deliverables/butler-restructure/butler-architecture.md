# AI 管家核心模块 · 架构说明与调用流程

> 项目：智学数研 · 迭代17　日期：2026-08-14

## 一、架构总览

在不动现有「Agent Kernel + 6 个 Skill」的前提下，叠加一层 **AI 管家调度层（Butler Orchestrator）**，让 AI 从「对话里的应答者」升级为「全域学习管家」。

```
┌────────────────────────── 前端（Vue 3 SPA）──────────────────────────┐
│  右栏管家面板 · 今日3件事 · 学情总览 · 错题本 · 报告 · 图谱 · 对话   │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ HTTPS · JWT
┌───────────────────────────▼─────────────────────────────────────────┐
│  FastAPI 网关（20+ router）                                          │
│   ├─ /api/butler/*          ← 新增：管家调度端点（butler_router）    │
│   ├─ /api/student/growth/*  ← AI 化：today-3/overview 文案 LLM 生成   │
│   └─ /api/student/*         ← 学情化：每日一题 + 事件上报             │
└────────┬───────────────────────────────────┬────────────────────────┘
         │ ①对话请求（不变）                   │ ②学习事件
┌────────▼───────────────┐          ┌─────────▼───────────────────────┐
│  Agent Kernel（不变）    │          │  ★ Butler Orchestrator（新增）   │
│  router/context/memory/ │          │  event_bus → dispatch → skills  │
│  rag/guard · Skill 调度  │          │  → ai_recommendations 落库     │
└────────────────────────┘          └─────────┬───────────────────────┘
                                              │ 复用
                              ┌───────────────┼────────────────────────┐
                              │ tools（工具集）│ state（状态记忆）         │
                              │ 学情/错题/出题 │ student_profiles 画像   │
                              │ 图谱/路由       │ + Redis 短期会话态      │
                              └───────────────┴────────────────────────┘
                                              │ 复用
                    ┌─────────────────────────┴─────────────────────────┐
                    │ services（fsrs/growth/copy_polish/learning_profile）│
                    │ skills（smart_quiz/socratic_solver/question_supply）│
                    │ providers（ModelRouter 星火主+DeepSeek 备）          │
                    └────────────────────────────────────────────────────┘
```

## 二、模块清单（`app/butler/`）

| 文件 | 职责 |
|------|------|
| `event_bus.py` | 学习事件总线：`emit()` 幂等落库 `learning_events`（`idempotency_key` 去重） |
| `tools.py` | 工具集：7 个工具（学情/到期错题/薄弱点/图谱依赖/变式题/路由/路径），`TOOL_SPECS` + `call_tool` 统一调度 |
| `state.py` | 状态记忆：`student_profiles` 长期画像 + Redis 短期会话态（反骚扰计数/去重时间戳） |
| `llm.py` | 管家 LLM 生成层：缓存 → LLM → 回退（`butler_llm_enabled` 总开关 + 10s 超时 + Redis 缓存） |
| `orchestrator.py` | 调度器：事件 → 决策（去重 + 反骚扰限额）→ 技能 → `ai_recommendations` 落库 |
| `skills.py` | 管家技能：今日计划/周报/错因诊断/路径规划/主动开场（规则骨架 + LLM 润色） |
| `gateway/butler_router.py` | 10 个 HTTP 端点 |

## 三、数据模型（新增 4 张表）

| 表 | 用途 | 关键字段 |
|----|------|---------|
| `student_profiles` | 学生画像（单行/用户） | `tags`/`weak_point_rank`/`learning_style`/`current_stage`/`profile_card` |
| `learning_events` | 学习事件（管家决策输入） | `event_type`/`source_type`/`payload`/`idempotency_key`/`status`/`retry_count` |
| `ai_recommendations` | AI 推荐记录（数据飞轮） | `kind`/`source`/`payload`/`user_feedback`/`shown_at`/`acted_at` |
| `exam_papers` + `exam_paper_items` | 试卷题库（套卷管理） | 套卷元信息 + 题目（题干/选项/答案/解析/知识点/难度/分值） |

**扩展既有表**：
- `error_records`：FSRS 字段已存在（`fsrs_stability`/`fsrs_difficulty`/`fsrs_retrievability`/`wrong_count`）
- `daily_questions`：改为「每生每天一题」（新增 `user_id`，唯一键 `(user_id, date)`）

## 四、调用流程（三条关键路径）

### 路径 1：事件驱动（判分 → 管家刷新画像）
```
POST /api/student/learning-events（判分）
  → 错题收录 + 掌握度更新 + 打卡（原有逻辑，不变）
  → event_bus.emit("quiz_judge", ...)   ← 新增挂载
  → orchestrator.dispatch(event)
      ├─ event_seen_recently 去重（8h）
      ├─ refresh_profile_from_mastery（静默更新 student_profiles 画像）
      └─ mark_event_seen + processed_at
  → 全程 best-effort，失败吞日志不阻塞判分
```

### 路径 2：请求内同步（页面实时拉取）
```
GET /api/butler/daily-plan
  → skills.daily_plan
      ├─ tools.query_due_errors（FSRS 到期）
      ├─ tools.query_weak_points（薄弱 Top）
      ├─ 规则骨架三件事（复习/专练/打卡）
      └─ llm.generate 逐条润色 title/why/benefit（缓存+超时+回退）
  → 返回 {tasks, greeting}
```

### 路径 3：管家面板聚合
```
GET /api/butler/dashboard
  → daily_plan（今日任务 + 开场白）
  → query_due_errors（到期错题）
  → query_weak_points（薄弱点）
  → copy_polish.polish（鼓励语）
  → 返回聚合 JSON 供右栏一次渲染
```

## 五、关键纪律（对齐方案）

1. **保留底线**：kernel / socratic_solver / smart_quiz / ModelRouter / fsrs / growth **零改动**，100% 复用。
2. **AI 优先 + 规则兜底**：所有面向学生的动态内容走 LLM，`copy_polish` / `butler.llm` 统一 10s 超时 + 异常回退模板 + Redis 缓存。
3. **事件驱动**：判分/错题/登录 → `learning_events` → orchestrator → 画像/推荐更新。
4. **反骚扰**：每日主动推送上限 `butler_proactive_limit=3`；同类事件 8h 去重；学生可在 `/butler/settings` 关闭。
5. **数字不编造**：LLM prompt 强约束「只润色不改数字」，规则骨架保证数据正确。

## 六、配置开关（`config.py`）

| 配置 | 默认 | 说明 |
|------|------|------|
| `growth_llm_polish` | `True`（已翻转） | 鼓励语/错因文案 LLM 润色总开关 |
| `butler_llm_enabled` | `True` | 管家 LLM 生成总开关 |
| `butler_proactive_limit` | `3` | 每日主动推送上限 |
| `butler_dedup_hours` | `8` | 同类事件去重窗口（小时） |
| `butler_polish_timeout_s` | `10` | 管家文案单次超时（秒） |

## 七、验证方式

```bash
cd services/api
./.venv/Scripts/python.exe -c "import app.main; print('import ok')"
# 启动后访问
curl http://localhost:8000/openapi.json | grep -o '"/api/butler[^"]*"' | sort
```
