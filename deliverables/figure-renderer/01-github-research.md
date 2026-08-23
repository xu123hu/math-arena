# GitHub 调研报告：数学参数化配图渲染

> 目标：为"高中数学题参数化配图渲染系统"（后端 Python 生成 SVG）选型与算法参考。
> 调研方式：web_search 检索 + 重点仓库源码分析（3 个并行调研主题）。
> 日期：2026-08

## 一、立体几何渲染库与 3D 投影算法

### 1.1 项目调研

| 项目 | Star | 许可 | 核心内容 | 评估 |
|---|---|---|---|---|
| [JSXGraph](https://github.com/jsxgraph/jsxgraph) | ≈1.1k | LGPL | `src/3d/View3D.js`、`Element3D`、`Transformation3D`：Rz∘Rx 轴测投影矩阵；交互式动态几何（2D/3D） | 投影数学可直接借鉴；但为浏览器 JS 库，后端无法调用 |
| [mathbox](https://github.com/unconed/mathbox) | ≈1.7k | MIT | WebGL/GLSL + three.js 数学可视化，正交/透视相机，GL_LINES 线框 | 仅借鉴正交/透视相机思路，无 SVG 输出 |
| [three.js](https://github.com/mrdoob/three.js) | 100k+ | MIT | `OrthographicCamera`（left/right/top/bottom 构正交矩阵，w=1 无透视除法）、`EdgesGeometry`+`LineSegments` 线框 | 投影数学标准可移植，但 JS/WebGL 不可后端化 |
| [svg3d](https://github.com/janbridley/svg3d) | 小 | MIT | Python 纯库：网格→SVG 矢量，含透视投影 | 形态最贴近后端需求；但功能简单、无隐藏线 |
| [pysometric](https://github.com/svoisen/pysometric) | 小 | MIT | Python 等轴测 3D 线稿（isometric 35.264°） | 仅固定视角、无透视/隐藏线 |
| [prideout《3D Wireframes in SVG》](https://prideout.net/blog/svg_wireframes/) | — | — | Python：相机矩阵 + 透视除法 + 凸体面法线隐藏线，后端生成 SVG 的最佳蓝本 | 博客示例非完整库，但算法完备 |

### 1.2 核心算法（已核实，直接落地）

**投影**（右手系，φ=仰角绕 X，θ=方位角绕 Z，与 JSXGraph View3D 顺序一致）：

```
绕 X：Rx(φ) = [[1,0,0],[0,cosφ,−sinφ],[0,sinφ,cosφ]]
绕 Z：Rz(θ) = [[cosθ,−sinθ,0],[sinθ,cosθ,0],[0,0,1]]
视图变换 M = Rx(φ)·Rz(θ)   （先绕 Z 再绕 X）
正交投影（丢 Z）：
  X = cosθ·x − sinθ·y
  Y = sinθ·cosφ·x + cosθ·cosφ·y − sinφ·z
屏幕（SVG y 向下）：u = cx + s·X，v = cy − s·Y
```

- Isometric 标准值：θ=45°，φ=arctan(1/√2)≈35.264°（本系统按国内教材习惯改用更小的 elev≈16°、yaw≈−28°，公式不变）。
- 透视（可选）：相机在原点朝 +z、焦距 f 时 `x' = f·x/z`（齐次裁剪除以 w），本系统默认关闭——正交投影保平行线，更适合解题配图。

**隐藏线/虚线（凸多面体 backface culling，O(F+E)，无需 z-buffer）**：
1. 面顶点按外法向逆时针排列，`n = (v1−v0)×(v2−v0)`；
2. 面可见 ⇔ `n·(v0−C) < 0`（C 相机位置；正交投影视线沿 −z 时退化为 `nz < 0`）；
3. 边邻接 ≥1 个前向面 → 实线；全部邻接面背向 → 虚线（或省略）。

### 1.3 借鉴结论
采用 JSXGraph/three.js 的投影矩阵数学 + svg3d/pysometric/prideout 的 Python 纯实现形态，**自研**：参数化顶点表+面表+边表驱动四棱锥/三棱锥/正方体/长方体/三棱柱，Rz∘Rx 轴测投影 + 面法线隐藏边判定。

## 二、函数图像绘制库

| 项目 | Star | 许可 | 核心算法 | 借鉴 |
|---|---|---|---|---|
| [function-plot](https://github.com/mauriciopoppe/function-plot) | ≈1.4k | MIT | `sampler` 用 math.js **区间算术**逐段求值，无界（含极点）或变化过大则二分递归细分至"近似线性"或最大深度；tan 极点因区间无界自动断开；region 用闭合 path+fill | 区间算术判间断 + 递归细分（Python 用中点线性误差替代区间算术） |
| [flot](https://github.com/flot/flot) | ≈6k | MIT | Canvas 折线；tickGenerator 按 0.1/0.2/0.5/1/2/5/10 nice 步长；flot-downsample LTTB 抽稀 | nice 刻度 + 大数据抽稀 |
| [d3-shape/d3-scale](https://github.com/d3/d3-array) | — | ISC | `line()` → M/L path；`ticks()/nice()` 用 tickIncrement：step 归一化到 1~10，按阈值 √2/√10/√50 选 1/2/5/10×10ⁿ（Heckbert 变体） | M/L path 生成 + nice tick 公式 |
| [ECharts](https://github.com/apache/echarts) | ≈61k | Apache-2.0 | 函数绘图靠外部数据喂 line series，LTTB 抽稀、轴刻度 nice 取整 | 抽稀策略 |
| [matplotlib](https://github.com/matplotlib/matplotlib) | ≈20k | BSD | `backend_svg.py` 把 Path(MOVETO/LINETO) 序列化为 `<path d>`，MaxNLocator 走 1/2/5 阶梯 | Path 语义直接映射 SVG |

**落地算法**（详见 `02-design.md` §4.3）：
1. 自适应采样：64 段起步 → 递归中点细分（`|f(mid)−(f(a)+f(b))/2| < tol≈1e-3`，深度上限 12）；
2. 间断断开：相邻采样 `|Δy| > 2.5×可视区高` 或非有限值 → 拆新 path（防 tan 假竖线）；
3. Heckbert nice ticks：`step = nf·10^exp`，f=range/10^exp 按阈值 1.5/3/7 选 nf∈{1,2,5,10}；
4. SVG 结构：viewBox + `M/L` 折线 path、区域填充"点列+底边闭合 Z"、轴/刻度用 line+text。

## 三、GeoGebra 与题库配图项目

| 项目 | Star | 许可 | 结论 |
|---|---|---|---|
| [GeoGebra](https://github.com/geogebra/geogebra) | ≈1.5k | GPL（部分非商用限制） | **不可作为替代**：无官方 Python 后端渲染，只有前端 iframe/JS API；node-geogebra 靠 Puppeteer 离屏（>10MB、不稳）；仅适合交互教学 |
| [TikZJax](https://github.com/kisonecat/tikzjax) | ≈3.2k | MIT | Emscripten 编译 TeX+TikZ→wasm（1MB+）浏览器内转 SVG；质量接近出版级。**启发**：结构化几何 DSL 作中间表示的思想与 figure_params JSON 一致；不必引入 wasm 全内核 |
| [Manim](https://github.com/ManimCommunity/manim) | ≈38k（3b1b 版 74k） | MIT | 3D 场景成熟、纯 Python 可后端批量；但面向视频动画、依赖 cairo/pango，过重 |
| [matplotlib](https://github.com/matplotlib/matplotlib) | ≈20k | BSD | mplot3d/Poly3DCollection 可画多面体出 SVG；3D 引擎简单、遮挡需手写 zorder——自研最直接的基座参考 |
| [GeoGen](https://github.com/ycpNotFound/GeoGen) | 小 | — | 平面几何题自动构造，未覆盖 3D 配图 |
| [JudgePeach/math-question-bank](https://github.com/JudgePeach/math-question-bank) | 小 | — | 本地高中数学题库（LaTeX+AI），无参数化渲染 |

**结论**：①GeoGebra 不可替代（浏览器依赖+许可+体积）；②**不存在现成的"参数化生成四棱锥/正方体 SVG"的成熟 Python 库**（svg3d/pysometric 过简，sverchok 依赖 Blender，manim/matplotlib 仅通用基座）；③采用"Python 自研渲染 + question_bank.figure_params JSON"是唯一满足后端/批量/确定/轻量的方案。

## 四、现有系统盘点（本仓库实测）

- `scripts/backfill_figures.py`：MiMo 生成 SVG → base64 data URI 写入 `question_bank.image`；只校验格式（长度/闭合），**不校验内容正确性** → 本次事故根源。
- 存量：**15 题**已有 AI 配图（gkb-2010-2022=12、gkb-2023=2、gkb-2024=1；choice=12/blank=3），另有 **73 题**无图但题干依赖图形。类型分布：长方体(外接球)、正/直三棱柱、正方体、三棱锥 P-ABC、四棱锥 P-ABCD、正三棱台、球。
- 数据链路：`quiz_item_from_bank()` 把 `QuestionBank.image` 透传为 `QuizItem.image` → **前端零改动**即可享受新渲染器输出。
- 迁移链头部为 `m2_014_error_record_image`，新迁移挂其后；测试基建完善（pytest + 独立 test 库），测试模式照搬 `tests/`。

## 五、最终技术路线（调研结论）

1. **自研纯 Python SVG 渲染器**（仅 math/xml 标准库），位于 `services/api/app/services/figure_renderer.py`；
2. 立体几何：参数化顶点/面/边表 + Rz∘Rx 轴测正交投影 + 面法线 backface culling 隐藏边虚线 + painter 排序半透明面填充；
3. 函数图像：AST 白名单安全求值 + 递归中点自适应采样 + 间断断开 + Heckbert nice ticks + 关键点/渐近线标注；
4. 存储：`question_bank.figure_params` JSONB 存参数，渲染确定性、可重放、可回归测试；
5. 提取：规则优先 + LLM 兜底（严格 JSON Schema prompt），渲染前后双重校验（参数校验 + 几何不变量校验），失败保留原图；
6. 参考仓库：JSXGraph（投影矩阵）、three.js（正交相机）、function-plot（采样）、d3-scale（tick）、prideout（隐藏线）、matplotlib（SVG 序列化）。

---
*说明：star 数为调研时近似值，会随时间波动。*
