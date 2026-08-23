# F13 可视化讲解 · 方案设计

> 状态：已评审定稿。基于 01-research.md 调研结论，结合现有 `figure_renderer.py` / `socratic_solver` /
> SSE 链路 / Vue3 前端现状设计。实现与验证见 03-implementation.md、04-verification.md。

## 1. 目标与非目标

**目标**：AI 引导式讲题过程中动态生成数学图形（函数图像/立体几何/解析几何），图形随讲解步骤
逐步出现（先构图 → 再标注），且全程**参数化、确定性、可校验**，SSE 协议向后兼容。

**非目标**（本期不做）：前端可拖拽交互（JSXGraph 级）、真 3D WebGL（mathbox 级）、连续补间动画
（Motion Canvas 级）、AI 自由生成 SVG。

## 2. 总体架构

```
题目 → [solver 求解] → 步骤计划(plan.steps)
              ↓（题目命中图形主题门控时）
        [figure planner] —— LLM 输出结构化图形指令 JSON
              ↓ 校验（validate_figure_params）+ 失败重试一次
        步骤合并：plan.steps[i].figure = {params, caption}
              ↓
   guide 阶段（引导文本流式下发后）
        [render_figure_frames] 派生渐进帧 → 确定性渲染 SVG → data URI
              ↓ 按场景限帧（防泄题）
        yield {"type":"figure", "data":{step_no, caption, frames:[{data_uri,label}]}}
              ↓
   agent_router：契约校验（kernel/figure_block）→ SSE `figure` 事件 → 信封落库 → 幂等重放
              ↓
   Vue3：messageModel 累积 figures[] → MathFigure.vue 帧导航渲染（淡入/点选/重播）
```

关键纪律（调研结论落地）：
- **AI 只输出结构化参数**（ChatTutor/AlphaGeometry/ToRA 范式），渲染全部走 figure_renderer；
- **图形失败不阻断讲解**（图丢了只丢图，token/card 照常）；
- **帧数随提示级别递增防泄题**（Perseus hint 分级范式）。

## 3. 图形生成方式：复用 figure_renderer + 分步帧派生

不重写渲染逻辑。新增两个纯函数（`services/api/app/services/figure_renderer.py`）：

### 3.1 `derive_figure_frames(fig) -> [{"figure": params, "label": str}]`

把一份**完整** figure_params 派生成 1~2 帧渐进序列（累计式，后帧在前帧上增加要素）。
每帧都是一份完整可独立渲染的 figure_params，复用 validate/render 全链路：

| 类型 | 帧 1（构图，无答案信息） | 帧 2（标注） | 退化单帧条件 |
|---|---|---|---|
| function | 坐标系 + 曲线（去 points/渐近线） | + 关键点/渐近线 | 无关键点且无渐近线 |
| triangle2d | 三角形三边 | + 外接圆/直角标记 | 无外接圆且无直角标记 |
| 立体类型 | 几何体轮廓（`show_labels=false`） | + 顶点字母标注 | 显式关标注 / 独立球 |
| sphere(独立) | 球 + 球心 O（构图要素） | — | 恒单帧 |

帧间几何布局一致（标注不参与 fit 变换），前端换帧不跳动。

### 3.2 `render_figure_frames(fig, step_no, caption, frame_limit) -> dict`

渲染每帧 SVG → 过 `check_svg_invariants`（fatal 即抛 FigureParamsError）→ `to_data_uri`，
产出 figure 事件载荷。`frame_limit=N` 只取前 N 帧（引导阶段限帧用）。

## 4. 流式输出协议：figure 事件

### 4.1 事件格式（skill 产出 → gateway 校验转发）

```
event: figure
data: {
  "step_no": 2,                    // 对应参考解步骤（可选）
  "caption": "画出 y=x²-2x-3 的图像", // 图形说明（可选，≤80 字）
  "frames": [                      // 1~2 帧，累计式
    {"data_uri": "data:image/svg+xml;base64,...", "label": "坐标系与曲线"},
    {"data_uri": "data:image/svg+xml;base64,...", "label": "标注关键点"}
  ],
  "figure_params": {...}           // 完整参数（调试/审计，前端不渲染）
}
```

- **多事件**：一次回答流中可多次出现（每个讲解步骤一张图），与 token 交织，顺序 = 讲解顺序；
- **data URI 而非裸 SVG**：沿用 question_bank.image 既有链路，前端 `<img>` 渲染，
  杜绝 innerHTML 注入面；
- **契约校验**：`kernel/figure_block.py`（对标 graph_block.py）——frames 非空且 ≤6、
  data_uri 前缀/大小上限、非法丢弃记日志**绝不 500**。

### 4.2 事件序列

新题流：`meta → status* → token* → figure? → token* → figure? → … → card → done`
（figure 落在对应讲解文本之后、卡片之前）。

### 4.3 向后兼容

- 旧前端：`applySseEvent` 对未知事件默认忽略（既有铁律）——无图照常讲题；
- 新前端 + 旧后端：无 figure 事件则不渲染，历史无 figure 块则 `figures=[]`；
- 历史回放：信封新增 `{"type":"figure", ...}` block，`_replay_response` 与 `fromHistory` 还原；
  旧前端遇未知 block 走 unknownBlocks 占位（不白屏）。

## 5. AI 触发机制：figure planner（solver 之后、guide 之前）

### 5.1 为什么不在 guide 流里让 AI 直接输出图形指令

guide 是逐句流式 + 逐句防泄题检查的链路，混入 JSON 会破坏流式节奏与泄题滑窗；
且引导文本生成时参考解是"隐藏上下文"，让同一 LLM 同时画图容易把答案画进图里。
**分离关注**（solver-then-guide 已有先例）：求解完成后单独跑一次 planner，
产物（验证过的 figure_params）在 guide 阶段按提示级别限帧发射。

### 5.2 门控（省调用、防无关配图）

题目命中图形主题正则才跑 planner（函数/二次/抛物线/零点/极值/最值/图像/几何/立体/
棱锥/棱柱/球/圆/椭圆/双曲线/抛物线/坐标/切线/三角形 等）。未命中 → 零额外 LLM 调用，
行为与现状完全一致。题目本身带图库配图（question_bank.figure_params）时亦可复用，
本期先接 planner 生成的图。

### 5.3 planner 契约

输入：题目 + 参考解步骤摘要（步骤号/断言）。输出 JSON 数组（无适合的图输出 `[]`）：

```json
[{"step": 2,
  "caption": "作出 y=x^2-2x-3 的图像，观察与 x 轴交点",
  "figure": {"type":"function","params":{
     "curves":[{"expr":"x**2-2*x-3","label":"y=x^2-2x-3"}],
     "x_range":[-3,5],"y_range":[-5,6],
     "points":[{"x":-1,"y":0,"label":"(-1,0)"},{"x":3,"y":0,"label":"(3,0)"},{"x":1,"y":-4,"label":"(1,-4)"}]}}}]
```

- 每个 step 至多 1 张图，整题至多 3 张（`_MAX_FIGURES_PER_PROBLEM`）；
- 每张图经 `validate_figure_params` 校验；非法 → 带错误消息反馈重试一次 → 仍非法丢弃该图；
- 图形类型优先级（planner prompt 明示）：**函数图像 > 立体几何 > 解析几何 > 平面几何**；
- 关键点只画题目给定或与当前步骤断言一致的（零点/极值点/交点/顶点），不画后续步骤结论；
- schema 说明复用 `FIGURE_SCHEMA_DOC`（单一事实来源，不复制粘贴）。

### 5.4 产物落位

`plan.steps[i].figure = {"params": {...}, "caption": "..."}` —— 随 tutor_sessions.plan 持久化，
regenerate/重放自然携带，无新增表、无迁移。

## 6. guide 阶段发射策略（帧数 × 场景，防泄题核心）

| 场景 | 发射时点 | 帧数 | 理由 |
|---|---|---|---|
| 新题开场（第 1 步引导） | GUIDE_OPENING 文本后 | 1 帧（构图） | 帮助审题；关键点=答案，不给 |
| 答对 → 下一步引导 | 文本后 | 先发**刚完成步**全帧（视觉确认）→ 再发下一步 1 帧 | 答对后展示答案性标注=奖励+巩固 |
| 主动要提示（hint） | 提示文本后 | 1 帧 | 三档提示均不给答案性标注 |
| 答错反馈（wrong） | 反馈文本后 | 1 帧 | 同上；图形帮定位，不泄底 |
| partial 追问 | 文本后 | 1 帧 | 同上 |
| 揭示/完成总结 | 总结文本后 | 全部步骤全部帧 | 学生已拿到完整解答，无泄题约束 |

实现为一个生成器助手 `_figure_events(session, step_no, frame_limit)`：
无图/渲染异常/不变量 fatal → 静默跳过（记日志），绝不打断 token 流。

## 7. 前端渲染：MathFigure.vue（零新依赖）

### 7.1 数据流

- `messageModel.js`：assistant 消息新增 `figures: []`；`applySseEvent` 处理 `figure` 事件
  （push，按 step_no 幂等去重）；`fromHistory` 从 `figure` block 还原；
- `MessageBubble.vue`：正文（IncrementalMarkdown）之后渲染 `MathFigure` 列表——
  "图形出现在对应讲解步骤旁边"（同气泡内、紧跟该步文本）。

### 7.2 组件设计（对标 manim-slides 帧导航 + reveal.js fragments）

```
┌────────────────────────────────┐
│ 📐 步骤 2 · 作出函数图像         │  ← caption + 步骤徽标
│ ┌──────────────────────────┐   │
│ │  <img :src="frames[cur]">│   │  ← 当前帧（Transition fade 淡入）
│ └──────────────────────────┘   │
│ ●───●  ▶重播  坐标系与曲线      │  ← 帧圆点（可点跳转）+ 当前帧 label + 重播
└────────────────────────────────┘
```

- **自动播放**：流结束后（status=done）从帧 0 起每 1.6s 自动推 1 帧至末帧；
  流式期间新帧到达即显示帧 0（跟随讲解节奏）；
- **手动控制**：帧圆点跳转、重播按钮；
- **单帧退化**：静态图（无控件）；
- **加载失败**：显示兜底文案 + 折叠的 figure_params 调试面板，绝不白屏；
- 动画：`<Transition name="figure-fade">` 纯 CSS，零依赖。

## 8. 后端集成点

1. `services/api/app/services/figure_renderer.py`：+`derive_figure_frames`、`render_figure_frames`；
2. `services/api/app/kernel/figure_block.py`（新）：`validate_figure_block` 契约校验；
3. `services/api/app/skills/socratic_solver/prompts.py`：+`FIGURE_PLANNER_SYSTEM/USER/RETRY`
   与 guide 提示的 `FIGURE_CONTEXT_BLOCK`（告知 LLM 本步配有图、图中有什么、禁止说出
   图中未显示的答案信息）；
4. `services/api/app/skills/socratic_solver/figures.py`（新）：planner 输出解析/校验/合并
   纯函数 + `_should_plan_figures` 门控；
5. `services/api/app/skills/socratic_solver/main.py`：planner 调用、步骤合并、
   `_figure_events` 发射（开场/答对/hint/wrong/partial/总结六个场景）；
6. `services/api/app/gateway/agent_router.py`：`figure` 事件转发 + 信封 block 落库 + 重放；
7. `services/api/app/skills/base.py`：事件文档更新（skill 可 yield figure）。

## 9. 图形类型优先级与示例

| 优先级 | 类型 | figure_params 示例要点 |
|---|---|---|
| 1 函数图像 | function | 二次函数零点/顶点标注；sin/tan 渐近线；两函数交点 |
| 2 立体几何 | cube/cuboid/pyramid/sphere... | 现有 8 类参数化几何体 + 外接球组合 |
| 3 解析几何 | function（多曲线） | 圆/椭圆方程转参数曲线、直线与圆锥曲线交点 |
| 4 平面几何 | triangle2d | 直角三角形/外接圆 |

## 10. 测试与验证计划

- **单测**（pytest，services/api/tests/）：
  - `test_figure_frames.py`：帧派生（function/triangle2d/立体/单帧退化）、帧 1 无答案性标注、
    确定性（同参数同 SVG）、frame_limit 截断、不变量 fatal 抛错；
  - `test_figure_block.py`：契约校验（合法/缺帧/坏 data_uri/超上限/非 dict → None）；
  - `test_socratic_figures.py`：planner 输出解析（JSON 提取/坏 JSON/步骤越界/重复去重）、
    门控正则、`_figure_events` 限帧与异常静默、场景发射（MockLLM 全旅程断言 figure 事件序）；
  - `test_graph_block.py` 风格的主链路：figure 事件落库/重放/非法丢弃不 500。
- **端到端验证**（04-verification.md）：函数题、立体几何题、解析几何题 3 道典型题
  （确定性渲染 + 不变量断言 + 纯文字 vs 可视化讲解对比 + 前端 mock 效果截图）。

## 11. 风险与对策

| 风险 | 对策 |
|---|---|
| planner 把答案画进图里 | 帧 1 确定性剥掉 points/标注；引导阶段恒 1 帧；planner prompt 明令只画当前步已知信息 |
| 额外 LLM 调用增加延迟 | 主题门控；非流式小调用（max_tokens~1200）；planner 失败静默降级为纯文字 |
| SVG data URI 体积 | 上限校验（figure_block）；460×330 典型 ~5KB，无压力 |
| 旧前端/旧数据兼容 | 未知事件忽略铁律 + unknownBlocks 占位 + 无图降级 |
| 图形与文本不同步 | 图紧随对应步骤文本之后发射（同一气泡、顺序一致）；帧自动播放对齐完成态 |
