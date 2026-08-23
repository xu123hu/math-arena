# F13 可视化讲解 · 验证报告

> 验证日期：2026-08。测试环境：Python 3.12 venv（services/api），PostgreSQL 54329 测试库，
> MockLLM 打桩（真实 figure_renderer 渲染、真实 SSE 事件链路）。

## 1. 测试矩阵

| 套件 | 用例数 | 结果 | 覆盖 |
|---|---|---|---|
| `tests/test_figure_frames.py` | 14 | ✅ | 帧派生（函数/平面/立体/单帧退化）、帧1无答案标注、确定性、frame_limit、不变量、非法参数 |
| `tests/test_figure_block.py` | 15 | ✅ | 契约校验（前缀/尺寸/帧数/类型/长度/非dict）、gateway 幂等重放、坏数据跳过不炸流 |
| `tests/test_socratic_figures.py` | 19 | ✅ | 主题门控、JSON 数组提取、planner 解析（越界/重复/封顶/部分有效/非法反馈）、全旅程五场景发射策略、planner 失败降级纯文字 |
| 回归 `test_socratic_solver.py` + `test_figure_renderer.py` | 101 | ✅ | 既有行为零回归 |
| **合计** | **149+** | ✅ | |

lint：改动文件 `ruff check` 全部通过（存量告警未触碰）。

## 2. 端到端全旅程（MockLLM，SSE 事件实录）

完整实录见 `samples/journey_events.txt`（`scripts/demo_f13_journey.py` 生成），摘要：

| 阶段 | 事件序 | figure 帧 | 防泄题验证 |
|---|---|---|---|
| ① 新题开场 | status → card(socratic_start) → token(引导) → **figure(步骤1)** | 1 帧 | ✅ 帧内容**无** `(-1,0)/(3,0)/(1,-4)` 标注 |
| ② 学生答对 | token(下一步引导) → **figure(步骤1)** → **figure(步骤2)** | 完成步 2 帧 + 下一步 1 帧 | ✅ 完成步含答案标注（视觉确认）；下一步构图帧无标注 |
| ③ 主动要提示 | token(提示) → **figure(步骤2)** | 1 帧 | ✅ 无答案标注 |
| ④ 直接看答案(一确) | token(确认话术) → card | 无 | ✅ 确认阶段不发图 |
| ⑤ 确认揭示 | token(总结) → **figure(步骤1全帧)** → **figure(步骤2全帧)** → card(complete) | 全部全帧 | ✅ 已拿到完整解答，无泄题约束 |

关键断言（测试固化）：开场 figure 在引导 token **之后**出现（图文顺序=讲解顺序）；
`meta.figures=2`（planner 产出计数）；planner 非主题题**零调用**（门控）；planner 两次非法输出 →
纯文字讲解不阻断。

## 3. 三题图形正确性校验（参数化渲染不变量断言）

`scripts/render_f13_samples.py`（可复跑），逐帧过 `check_svg_invariants`：

| 题 | 图形 | 帧 1 | 帧 2 | 不变量 |
|---|---|---|---|---|
| P1 函数题：作 y=x²-2x-3 图像求交点 | function | 坐标系与曲线 | +零点(-1,0)(3,0)/顶点(1,-4) | ✅ PASS（XML/尺寸/有限值） |
| P2 立体几何：棱长2正方体外接球 | sphere+solid(cube) | 几何体轮廓（无字母） | +顶点标注（A…D₁、O） | ✅ PASS（含虚线隐藏边） |
| P3 解析几何：直线 y=x-1 与圆 x²+y²=4 | function×3曲线 | 圆+直线 | +交点 A(1.823,0.823)/B(-0.823,-1.823) | ✅ PASS |

数学交叉验证（脚本内程序化复核）：交点坐标 = (1±√7)/2 代入 x²+y²=4 与 y=x-1 均满足；
外接球半径 = a√3/2 = √3（参数即公式值）。

## 4. 输出对比：纯文字 vs 可视化讲解

以 P1 为例（同一引导步骤）：

| 维度 | 纯文字（现状） | 可视化（F13） |
|---|---|---|
| 开场 | 「先回忆一下：二次函数图像是什么形状？开口方向由谁决定？」 | 同一句话 + **坐标系与抛物线构图帧**（无答案标注） |
| 答对第 1 步 | 「答得漂亮！下一步……」 | 同上 + **完整抛物线图（顶点标注出现）** 视觉确认 |
| 卡在求交点 | 「解方程 x²-2x-3=0……再想想」 | 同上 + **圆点标注逐步揭示**，学生"看见"答案的位置关系 |
| 完整解答 | 纯文本步骤 | 文本 + 全部图形全帧（含零点/顶点标注） |

## 5. 效果图

- **帧 PNG**（resvg 渲染，`effect-images/`）：6 张单帧（每题 2 帧）；
- **分步对比 PNG**：`p1_function_steps.png` / `p2_solid_steps.png` / `p3_analytic_steps.png`
  （帧1|帧2 左右并排，直观呈现"先构图→再标注"）；
- **SVG 源**：`samples/*.svg`（可用浏览器/VS Code 直接打开）；
- **交互预览**：`samples/preview.html` —— 双击打开即可体验帧自动播放/圆点跳转/重播
  （无需任何服务器，内嵌真实渲染 SVG + 与 MathFigure.vue 一致的帧导航逻辑）；
- **组件渲染验证**：`frontend-f13/demo/ssr-check.mjs` SSR 冒烟 10 项断言全 PASS
  （组件真实渲染出图形卡 DOM：步骤徽标/caption/帧 label/data URI/圆点/重播）。

## 6. 环境限制与替代验证说明

本会话沙箱**禁止命名管道**（Chromium mojo 与 playwright daemon 均无法启动）且前端实际目录
`D:\frontend` 在工作区外（写入需用户授权，已取消）。因此：

- ❌ 无法在沙箱内启动浏览器截图 → ✅ 改用 resvg-js（工作区内安装）无浏览器渲染 PNG；
- ❌ 无法直接改 `D:\frontend` → ✅ 交付 `frontend-f13/` 安装包（4 个文件，含精确补丁与覆盖说明）；
- ❌ 无法跑真实前端页面 → ✅ Vue SSR 冒烟（真实组件 + 真实渲染数据，DOM 断言）+ preview.html
  （同一交互逻辑的浏览器内演示）+ mock 补丁（应用后 `npm run dev` 即演示）。

**人工复核清单**（交付后建议执行，约 5 分钟）：
1. 按 `frontend-f13/README.md` 应用 4 个文件到 `D:\frontend`；
2. `npm run dev`（mock 模式）发任意消息 → 确认 socratic 回复气泡内出现图形卡、
   done 后自动从「坐标系与曲线」过渡到「标注关键点」、可点帧圆点/重播；
3. 双击 `deliverables/f13-visual-guidance/samples/preview.html` 核对 3 题图形数学正确性
   （P1 零点 ±1/3、顶点 (1,-4)；P2 外接球过 8 顶点；P3 交点 A/B 位置）。

## 7. 已知边界与后续方向

- 引导/提示/纠错场景恒 1 帧（构图），标注帧仅在答对确认与揭示时出现——这是**刻意**的防泄题设计；
- 解析几何复用 function 多曲线表示（圆=上下半圆），曲率在端点处采样加密，视觉连续；
- 后续可扩展：帧间补间动画（Motion Canvas 式）、图形交互（JSXGraph 式拖拽）、
  planner 主题门控改为小模型分类器、几何题辅助线（切点/法线）的纯计算层（geometric 式）。
