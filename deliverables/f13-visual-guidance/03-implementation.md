# F13 可视化讲解 · 实现说明与使用指南

> 对应设计：02-design.md。全部后端改动在 `services/api`，前端交付包在 `frontend-f13/`。

## 1. 改动文件清单

### 后端（services/api）

| 文件 | 改动 | 说明 |
|---|---|---|
| `app/services/figure_renderer.py` | 扩展 | +`derive_figure_frames`（完整图→渐进帧）、+`render_figure_frames`（帧渲染→figure 事件载荷）。渲染核心零改动 |
| `app/kernel/figure_block.py` | 新增 | figure 事件契约校验 `validate_figure_block`（对标 graph_block，非法丢弃不 500） |
| `app/skills/socratic_solver/figures.py` | 新增 | 图形规划纯函数：`should_plan_figures` 主题门控、`extract_json_array`、`parse_figure_plan`、`merge_figures_into_plan` |
| `app/skills/socratic_solver/prompts.py` | 扩展 | +`FIGURE_PLANNER_SYSTEM/USER/RETRY`（复用 FIGURE_SCHEMA_DOC 单一事实来源）、+`FIGURE_CONTEXT_BLOCK` |
| `app/skills/socratic_solver/main.py` | 扩展 | 求解后 planner 调用与步骤合并；`_figure_events`/`_figure_context_block`/`_guide_content`；六个场景限帧发射；meta 增 `figures` 计数 |
| `app/gateway/agent_router.py` | 扩展 | `figure` 事件转发（契约校验）→ SSE；信封 `figure` block 落库；幂等重放还原 |
| `app/skills/base.py` | 文档 | skill 事件产出清单补 figure |
| `tests/test_figure_frames.py` | 新增 | 帧派生/渲染载荷/确定性/限帧 14 例 |
| `tests/test_figure_block.py` | 新增 | 契约校验 + gateway 重放 15 例 |
| `tests/test_socratic_figures.py` | 新增 | planner 解析/门控/发射策略/全旅程 19 例 |
| `scripts/render_f13_samples.py` | 新增 | 3 道典型题帧渲染 → SVG + demo 数据 + 不变量断言 |

### 前端（frontend-f13/ 交付包，按 README 应用到 D:\frontend）

| 文件 | 说明 |
|---|---|
| `src/components/chat/MathFigure.vue` | 新组件：帧渐进揭示（自动播放/圆点导航/重播），零新依赖 |
| `patches/messageModel.js` | 完整替换版：`figures[]` + figure 事件归约 + 历史还原 |
| `patches/frontend-patches.md` | `MessageBubble.vue`（2 处）与 `mock/server.js`（3 处）精确补丁 |
| `demo/` | 独立演示/验证项目（SFC 编译 + SSR 冒烟 + 静态预览），不依赖前端目录 |

## 2. 核心 API

### 2.1 分步渲染（figure_renderer）

```python
derive_figure_frames(fig)          # -> [{"figure": 完整 figure_params, "label": str}, ...] 1~2 帧累计式
render_figure_frames(fig, *,
    step_no=None, caption="", frame_limit=None) -> dict   # -> figure 事件 data 载荷
```

帧派生规则：function（帧1 坐标系+曲线 → 帧2 +关键点/渐近线）、triangle2d（三边 → +外接圆/直角标记）、
立体类型（轮廓 `show_labels=false` → +顶点标注）、独立球单帧。帧 1 恒不含答案性标注（防泄题）。
每帧过 `check_svg_invariants`，fatal 抛 `FigureParamsError`（调用方丢弃整图，不阻断讲解）。

### 2.2 figure 事件契约（kernel/figure_block）

```json
{"step_no": 2, "caption": "…(≤80字)",
 "frames": [{"data_uri": "data:image/svg+xml;base64,…", "label": "坐标系与曲线"}, …],  // 1~6 帧
 "figure_params": {…}}   // 调试/审计，前端不渲染
```

校验：data_uri 前缀/≤200KB、frames 1~6、step_no 正整数、caption ≤80、strict 类型；
非法降级丢弃 + 记日志，绝不影响 SSE 主链路。

### 2.3 图形规划（socratic_solver）

- **门控**：题目命中 `FIGURE_TOPIC_RE`（函数/图像/几何/圆/坐标/…）才调用 planner，未命中零额外调用；
- **契约**：planner 输出 JSON 数组 `[{"step", "caption", "figure"}]`，整题 ≤3 图、
  每图过 `validate_figure_params`，全部非法反馈重试一次、部分非法丢弃坏条目；
- **合并**：`plan.steps[i].figure = {"params", "caption"}` 随 tutor_sessions.plan 持久化
  （无新表、无迁移，regenerate/重放自动携带）。

### 2.4 发射策略（帧数 × 场景 = 防泄题核心）

| 场景 | 帧数 |
|---|---|
| 新题开场 / 下一步引导 / hint / 答错反馈 / partial 追问 | 1 帧（构图） |
| 答对后：刚完成步（视觉确认） | 全帧 |
| 揭示/完成总结 | 全部步骤全部帧 |

## 3. Prompt 工程

- `FIGURE_PLANNER_SYSTEM`：只输出 JSON 数组、图形类型优先级（函数>立体>解析>平面）、
  标注只含"当前步及之前已知"信息（禁止把答案画进图）、顶点命名与题干一致、
  schema 直接拼接 `FIGURE_SCHEMA_DOC`（单一事实来源）；
- `FIGURE_CONTEXT_BLOCK`：guide 链每步配图时注入——告诉引导 LLM 图已展示、图中内容，
  可引用图形但禁止说出图中未标注的信息；
- 引导文本生成链路本身零改动（图形指令不进流式文本，planner 与 guide 解耦）。

## 4. 使用步骤

```powershell
# 后端：无需迁移、无需新依赖
cd services/api
.venv\Scripts\python.exe -m pytest tests/test_figure_frames.py tests/test_figure_block.py tests/test_socratic_figures.py -q   # 49 例
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000 --reload

# 样例渲染（效果图 + demo 数据）
.venv\Scripts\python.exe -m scripts.render_f13_samples

# 前端：按 frontend-f13/README.md 应用 4 个文件到 D:\frontend
cd D:\frontend
npm run dev            # mock 模式默认 socratic 回复即含 2 帧抛物线演示
# 连真实后端：$env:VITE_REAL_API=1; npm run dev

# 效果预览（无需服务器，双击打开）
start D:\math-arena\deliverables\f13-visual-guidance\samples\preview.html
```

## 5. 兼容性

- **SSE 向后兼容**：figure 为新增事件类型；旧前端对未知事件默认忽略（既有铁律），
  无 figure 事件时行为与现状完全一致（旧对话正常）；
- **历史兼容**：新前端 + 旧数据 → `figures=[]` 优雅降级；旧前端 + 新数据 →
  未知 block 走 unknownBlocks 占位（不白屏）；
- **降级链**：主题不命中 → 不调 planner；planner 失败 → 纯文字讲解；
  渲染失败 → 丢图不丢话；契约非法 → gateway 丢弃，done 照发。
