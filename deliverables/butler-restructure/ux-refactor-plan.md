# 练题中心 / 错题详情 / 知识图谱 · UX 重构方案

> 日期：2026-08-14　基于：用户截图 + 调研 + 前端用户体验工程 skill

## 一、问题诊断

### 1. 练题中心（PracticeLabView）— 用户截图 1

| 问题 | 现状 | 根因 |
|------|------|------|
| 硬编码知识点 | 「今日训练 · 5 题解三角形」无法换 | UI 写死，缺知识点选择入口 |
| 三个模式一个都用不了 | 「15 分钟 / 60 分钟 / 考前冲刺」纯装饰 | `mode` 参数后端支持，前端没实现路由与时长 |
| 没做沉浸式 | 列表 + 推荐占满一屏 | 缺「单题大屏」全屏视图 |

### 2. 错题详情（ErrorsView 详情区）— 用户截图 2

| 问题 | 现状 | 根因 |
|------|------|------|
| 「暂无正解文本」 | 答案字段空 | 判分时没存正解（只有题干 + 学生答案） |
| 布局拥挤 | 列表 + 详情同页，左原题右分析挤一起 | 缺独立详情页路由 |
| 缺 AI 答疑 | 只有错因文本，无引导式讲解 | 错题 AI 只是错因，没接「苏格拉底引导重做」 |

### 3. 知识图谱（GraphView）— 用户截图 3

| 问题 | 现状 | 根因 |
|------|------|------|
| 节点编号难看 | 显示 `MATH-G1-FUNC-001` | 后端 `knowledge_points.code` 是内部编码，前端直接展示了 |
| 学生看不懂 | 没有人类可读名称 | 应优先用 `kp_name`（"函数的概念与基本初等函数"） |
| 先决关系不可见 | 看不到锁/开锁状态 | 缺 ALEKS 风格的可视化 |

## 二、调研汇总（核心 5 + 之前 13+ = 18+ 项目）

### 练题（核心 3）

- **Anki**（ankitects/anki，~20k stars，AGPLv3/MIT）：flashcard 记忆王者；极简 study screen（question + answer + confidence buttons）；FSRS 间隔重复（项目已用）；SR 算法模板。
- **Quizlet**（商业）：Magic Notes（笔记→卡片 AI 生成）、Learn/Test 模式（自适应难度切换）、Expert Solutions（AI 答案生成）。
- **Brainscape**（商业）：adaptive 重复间隔；可视化掌握度色条。

### 错题 + AI 答疑（核心 2）

- **Khanmigo**（可汗学院 AI 导师，OpenAI 合作）：苏格拉底式引导——"你目前是怎么想的？"先确认思路；卡住时拆小步；答错时**不直接说错**，指出"哪一步值得再检查"；每轮 ≤5 句（导师话少学生话多）；**强约束 prompt**："即使明确索要也不直给"必须最前+绝对措辞，否则三轮内模型会缴械。
- **Photomath**（商业）：扫描题 → 分步解题 + 解释 + 引导变式。

### 知识图谱（核心 2）

- **ALEKS**（McGraw Hill，Knowledge Space Theory）：**The Pie Chart** 是最 distinctive UI——每个 topic 一个 slice，已掌握填色；Knowledge Space（先决关系图）；未具备先决条件的 topic "锁住"，掌握后"解锁"；初始评估 25-30 题 + 定期 knowledge check。
- **IXL**（商业）：分章节 → 技能树；掌握度热力图。

### 之前策略调研（13+，Agent/AI 方向相关）

LangGraph（35k）/Dify（151k）/iflytek-astron-agent（8.6k，**同生态**）/Lobe Chat（49k）/py-fsrs（464）/ankitects-anki（20k）/DeepKnowledgeTracing（306）/Knowledge_Tracing /mem0ai-mem0（30k）/chrispiech-DKT /MrMaks-KT collection 等，已在《AI 管家化重构总方案 v3.0》§3.1 列过。

## 三、重构方案

### 页面 1：练题中心重构（PracticeLabView）

**设计目标**：Quizlet 的模式切换 + Anki 的单题大屏沉浸。

**UI 改版**：
- 顶部 Tab 三模式**真工作**：
  - **15 分钟模式**（5 题 + 倒计时 15:00）
  - **60 分钟模式**（20 题 + 倒计时 60:00）
  - **考前冲刺**（真题 12 道 + 倒计时 90:00）
- 知识点选择：默认薄弱 Top1 + 手动下拉切换（带章节树，参考 ALEKS Knowledge Space）
- **沉浸式单题**：选模式后进入全屏单题视图，左侧题干+学生答题区，右侧进度条 + 倒计时 + 立即判分按钮；提交后弹出「判定 + AI 讲解 + 下一题」

**实施**：
- `PracticeLabView.vue` 重写（路由 /practice-lab → 拆 /practice-lab/setup 选题 + /practice-lab/solve 沉浸 + /practice-lab/result 结算）
- 复用现有 `/student/practice/start`（加 mode + kp 参数）+ `/student/practice/submit`
- `butler/recommend` 提供薄弱 Top 推荐

### 页面 2：错题详情独立页 + AI 答疑

**设计目标**：Anki 风格的「列表独立 + 详情专注」，Khanmigo 苏格拉底答疑。

**UI 改版**：
- **列表页**（ErrorsView）：只显示列表（错题热力图 + 列表 + 筛选），**移除详情内嵌**
- **详情页**（新组件 `ErrorDetailView.vue`，路由 `/errors/:id`）：左原题+正解，右 AI 问诊 + **AI 答疑 chat**（苏格拉底）
- AI 答疑 prompt 强约束：「即使明确索要也不直给」，每轮 ≤5 句

**实施**：
- 拆路由：`/errors`（列表）+ `/errors/:id`（详情）
- **新后端接口**：
  - `GET /api/butler/error-detail/{id}`：返回 AI 生成的正解（之前缺失）
  - `POST /api/butler/error-tutor`：AI 答疑（苏格拉底引导式 chat），输入学生消息，返回 tutor 回复
- 复用已有 `butler/error-diagnosis`（错因）+ 新增 `error-detail`/`error-tutor`

### 页面 3：知识图谱人性化

**设计目标**：ALEKS 风格可读图谱。

**UI 改版**：
- 节点**显示 `kp_name`**（"函数的概念与基本初等函数"），`code` 作为 hover tooltip
- 借用 ALEKS pie chart 思路：右侧「我的学习版图」用 ring chart 显示章节掌握度
- 先决关系：连线 + 锁/开锁状态（未具备先决条件 = 灰色 + 🔒 图标）

**实施**：
- `GraphView.vue` 模板改用 `kp_name` 替代 `kp_code`（kg-graph 组件 props 调整）
- 加 hover tooltip 显示完整 code + 描述
- 后端 `/student/knowledge-graph` 现有结构可能够用（确认 kp_name 返回）

## 四、实施计划

| 阶段 | 内容 | 估时 | 风险 |
|------|------|------|------|
| 0 | **用户确认优先级** | - | - |
| 1 | 知识图谱人性化（最小改动、最快见效） | 1h | 低 |
| 2 | 错题详情独立页 + AI 生成正解 | 2h | 中（后端新接口） |
| 3 | 错题 AI 答疑 chat（苏格拉底） | 4h | 中高（LLM 强约束 prompt） |
| 4 | 练题中心重写（3 模式 + 沉浸） | 6h | 高（前端重构最大） |

## 五、需要你确认

1. **接受这个方案？** （页面 1/2/3 的设计 + 阶段计划）
2. **页面优先级**？建议：先做 #1（最快见效）→ #2 → #3
3. **AI 生成正解 + AI 答疑**：这两个功能需要**后端新接口**（`/butler/error-detail/{id}`、`/butler/error-tutor`），是否一起做？
4. **不想做的页面可以跳过**，告诉我。

## 六、复用的现有能力（不重写）

- 后端 AI 管家中枢（`app/butler/`）：事件总线、工具集、LLM 生成层（缓存 + 10s 超时 + 回退）、苏格拉底 skill 可复用
- 现有接口：`butler/error-diagnosis`（错因）、`butler/recommend`（变式）、`practice/start`、`practice/submit`、`knowledge-graph`
- 前端已有：`V4Layout` 右栏面板、设计 tokens（v4 + 别名兼容）、玻璃卡风格