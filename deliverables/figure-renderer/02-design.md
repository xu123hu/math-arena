# 参数化配图渲染系统 — 方案设计

> 项目：math-arena 高中数学题库配图治理
> 日期：2026-08（M2 迭代）
> 状态：设计定稿，实现见 `services/api/app/services/figure_renderer.py`

## 1. 背景与目标

现有链路 `scripts/backfill_figures.py` 让 MiMo 直接生成 SVG（透视线框风格），只校验格式不校验内容。
实测 15 道高考真题配图中出现"四棱锥顶点 P 画在底面内部"、"透视关系混乱"等错误。
本方案改为：**大模型只负责从题干提取结构化参数（可校验、可重试），渲染全部由代码按参数精确计算**。

目标（硬性）：
- 同一组参数 → 永远同一张 SVG（确定性，可回归测试）；
- 立体几何透视正确：顶点在底面上方、可见边实线、被遮挡边虚线；
- 函数图像数值精确：自适应采样、渐近线断开、刻度 nice；
- 不引入任何前端/浏览器依赖，纯 Python 标准库生成 SVG 字符串；
- 保留 `question_bank.image` 字段语义（前端零改动），新增 `figure_params` JSONB 存参数。

## 2. 支持的图形类型（v1 清单）

| type | 说明 | 典型题目 |
|---|---|---|
| `cube` | 正方体 | 2022 理科 15（8 个顶点选 4 点） |
| `cuboid` | 长方体 | 2010 理 7（2a×a×a 外接球）、2017 理 15（3×2×1） |
| `triangular_prism` | 三棱柱（正/直/一般） | 2010 理 10（正三棱柱）、2016 理 11（直三棱柱 AB⊥BC） |
| `quad_pyramid` | 四棱锥 P-ABCD | 2023 甲卷理 11（底面正方形 AB=4） |
| `tri_pyramid` | 三棱锥 P-ABC | 2023 甲卷文 10（正三角形底面）、2021 理 11（O-ABC） |
| `tri_frustum` | 三棱台 | 2024 新课标 II 7（AB=6, A₁B₁=2） |
| `sphere` | 球/外接球（可内接几何体） | 2010 理 7、2016 理 4、2017 理 15 |
| `polyhedron` | 通用多面体（vertices/faces 自描述） | 兜底：任意凸多面体 |
| `function` | 函数图像（多曲线/关键点/渐近线） | 二次函数、三角函数、导数对比 |
| `triangle2d` | 平面三角形（可带外接圆/直角标记） | 备用 |

## 3. 参数结构（figure_params）

```json
{
  "version": 1,
  "type": "quad_pyramid",
  "params": { "base_w": 4, "base_d": 4, "height": 2.8, "apex": "P", "base": ["A","B","C","D"] },
  "labels": { "P": "P", "A": "A", "B": "B", "C": "C", "D": "D" },
  "view": { "yaw": -28, "elev": 16, "perspective": null, "scale": 1.0 },
  "size": [400, 300],
  "style": { "hidden": "dashed", "fill_faces": true, "show_labels": true }
}
```

各类型 `params` 结构：

- `cube`: `{ "a": 2 }`
- `cuboid`: `{ "a": 2, "b": 1, "h": 1 }`（长 a、宽 b、高 h；命名 ABCD-A₁B₁C₁D₁）
- `triangular_prism`: `{ "base": "equilateral"|"right"|"custom", "side": 2, "ab": 6, "bc": 8, "height": 3, "vertices": [[x,y],...] }`（命名 ABC-A₁B₁C₁）
- `quad_pyramid`: `{ "base_w": 4, "base_d": 4, "height": 2.8, "apex": "P", "base": ["A","B","C","D"], "apex_pos": [x,y,z]? }`（缺省 apex 在底面中心正上方）
- `tri_pyramid`: `{ "base": "equilateral"|"custom", "side": 2, "base_points": [[x,y],...], "apex": "P", "apex_pos": [x,y,z] }`
- `tri_frustum`: `{ "bottom_side": 6, "top_side": 2, "height": 2.5 }`
- `sphere`: `{ "r": 1.5, "center": [0,0,0], "center_label": "O", "solid": {"type": "cube", "params": {...}} | null, "solid_shift": [0,0,0] }`
- `polyhedron`: `{ "vertices": {"A":[x,y,z],...}, "faces": [["A","B","C"],...], "extra_edges": [["A","C"],...] }`
- `function`: `{ "curves": [{"expr": "x**2-2*x+1", "label": "y=x²−2x+1", "color": "#1f5fbf", "domain": [xmin,xmax]}], "x_range": [-4,4], "y_range": [-3,5], "axes": "center", "ticks": {"x": 1, "y": 1} | null, "points": [{"x":1,"y":0,"label":"(1,0)","mark":true}], "asymptotes": {"x":[1.0]}, "grid": false }`
- `triangle2d`: `{ "points": {"A":[0,0],"B":[3,0],"C":[0,4]}, "right_angle": "A"|null, "circumcircle": true|false }`

**设计约定**
- 3D 坐标系：底面在 z=0 平面，几何体中心在原点附近，yaw/elev 单位度。
- 顶点命名跟随题干（P-ABCD、A₁ 等），`labels` 缺省用键名。
- 所有长度按比例归一化后由 `scale`+画布尺寸自适应，防止参数不当导致溢出。

## 4. 渲染技术选型

### 4.1 选型对比（调研依据见 01-github-research.md）

| 方案 | 后端可用 | 确定性 | 依赖 | 结论 |
|---|---|---|---|---|
| JSXGraph | 否（浏览器 JS） | 是 | 前端 | 仅借鉴其 3D 视图数学 |
| GeoGebra | 否（无官方 Python 渲染，Puppeteer 离屏 >10MB，许可受限） | 是 | 浏览器 | 不采用 |
| mathbox / three.js | 否（WebGL） | 是 | 前端 | 仅借鉴投影公式 |
| TikZJax | 否（wasm 1MB+，浏览器内执行） | 是 | wasm | 借鉴其"结构化 DSL→SVG"思想 |
| Manim | 是 | 是 | cairo/pango 重 | 过重（面向动画），不采用 |
| matplotlib mplot3d | 是 | 是 | numpy+matplotlib | 3D 引擎简陋，隐藏面需手写 zorder，仅作基座参考 |
| **自研纯 Python SVG** | **是** | **是** | **仅标准库 math/xml** | **✅ 采用** |

### 4.2 立体几何投影（核心算法）

**轴测正交投影**（默认；透视可选）：

```
旋转矩阵：先绕 Z 轴转 yaw(θ)，再绕 X 轴转 elev(φ)
  x' = x·cosθ − y·sinθ
  y' = x·sinθ + y·cosθ
  y''= y'·cosφ − z·sinφ
  z''= y'·sinφ + z·cosφ     ← 深度值（用于 painter 排序）
屏幕坐标（SVG y 轴向下）：
  sx = cx + scale·x'
  sy = cy − scale·y''
```

- 默认视图 `yaw=-28°, elev=16°`：呈现"右前上方"视角，顶面可见，符合国内教材画法。
- 可选透视：`sx *= f/(f−z'')`，默认关闭（正交投影保证平行线平行，更适合解题图）。
- 参考：JSXGraph View3D 的 Rz/Rx 轴测实现与 isometric（θ=45°, φ≈35.264°）约定；本系统按教材习惯改用更小的 elev。

**隐藏线/虚线判定（凸多面体 backface culling）**：
1. 构建时保证每个面的顶点序为**外法向**（从体外看逆时针）。
2. 视图方向 `d` = 旋转矩阵的转置作用在 (0,0,1) 上（场景→相机方向）。
3. 面可见 ⇔ `n·d > 0`（n 为面外法线）。
4. 边可见 ⇔ 存在相邻可见面；**所有相邻面均不可见 → 画虚线**（stroke-dasharray）。
5. 面填充按 z'' 从远到近 painter 排序，仅填可见面（半透明浅色，增强立体感）。

该算法对凸多面体严格正确（调研结论②的落地：正交投影下退化为面法线 z'' 分量判据，本实现用 n·d 更通用、兼容透视）。

### 4.3 函数图像（核心算法）

1. **表达式安全求值**：`ast.parse` 白名单（Expression/BinOp/UnaryOp/Call/Name/Constant），仅允许 math 函数（sin/cos/tan/exp/log/sqrt/pow/abs）与常量 pi/e，**拒绝一切非法语法与任意代码执行**。
2. **自适应采样**（借鉴 function-plot sampler）：
   - 定义域均分 64 段起步；
   - 递归中点细分：`|f(mid) − (f(a)+f(b))/2| < tol`（tol≈1e-3，对应亚像素误差）则段内近似线性停止，否则继续二分（深度上限 12）；
   - **间断断开**：相邻采样 `|Δy| > jump_threshold`（默认 >2.5×可视区高）或任一 y 非有限（tan 在 π/2 等）→ 结束当前 `<path>` 另起，避免画出竖直渐近线假线。
3. **nice ticks（Heckbert）**：step = nf·10^exp，nf∈{1,2,5,10} 按 f=range/10^exp 与阈值 1.5/3/7 选取；刻度标签小数位自适应（整数值不带 .0）。
4. **关键点**：`points` 参数直接投影画圆点+标签；`asymptotes` 画灰色虚线。
5. **多曲线**：curves 数组（如原函数+导函数对比），各自采样、配色区分。

## 5. 与现有系统的集成

```
question_bank
├── image          JSONB  保留：渲染后的 data:image/svg+xml;base64 URI（前端 img 直接显示）
└── figure_params  JSONB  新增：结构化参数（本方案的核心存储）

渲染链路（前端零改动）：
figure_params → figure_renderer.render(figure) → SVG 字符串
             → base64 data URI → question_bank.image[0]
             → quiz_item_from_bank() 已透传 image 到 QuizItem.image（无需改动）
```

- 迁移 `m2_015_figure_params`（挂在 m2_014_error_record_image 之后，幂等 add_column）。
- 模型 `QuestionBank.figure_params: JSONB nullable`。
- 批处理脚本 `scripts/backfill_figure_params.py`：
  1. 候选筛选：`image` 非空（现存 15 题）∪ 题干命中配图关键词（现存 73 题候选中可挑选）；
  2. 参数提取：**规则提取优先**（针对已知题型模板：外接球/棱锥/棱台模式，正则+数值解析，100% 可校验）→ 规则未命中走 **LLM 提取**（DeepSeek，prompt 内置全部类型 JSON Schema，要求只输出 JSON）；
  3. 参数校验：`validate_figure_params()`（类型白名单、数值域、标签集合一致、顶点唯一性）；
  4. 渲染 + **几何不变量校验**（§6）；
  5. 校验通过才写库：更新 `figure_params`、替换 `image[0]`、`annotate_meta.figure_gen = {method: "parametric", ...}`；失败保留原图并记录 `status=failed`；
  6. `--dry-run` 只渲染到本地文件不写库；`--method rules|llm|auto` 可选。
- 失败安全：LLM 提取失败/渲染校验失败 → 原图不动，绝不覆盖成坏图。

## 6. 质量保证（几何不变量校验）

渲染后自动断言（失败即弃用该参数组）：
- SVG 可被 xml.etree 解析，根为 `<svg>`，无 NaN/Inf 坐标，size 在 [200,800]×[150,600]；
- 锥体：顶点 P 的屏幕 y < 底面所有顶点屏幕 y（**P 必须在底面上方**——本次事故的直接防复发断言）；
- 底面顶点投影构成凸多边形（逆时针凸包校验）；
- 棱柱：上下底面对应点投影不重合（无退化视图）；侧棱无交叉（按 x 排序检查）；
- 所有标注顶点数量与 params 一致；dashed 边至少存在（立体图必有隐藏边，除非视角退化）。

## 7. 单元测试（tests/test_figure_renderer.py）

- 投影数学：单位立方体在 isometric 视角下的顶点屏幕坐标（对拍手工计算值）；
- 隐藏边：默认视角正方体恰好 3 条虚线边（后下左），四棱锥 P-B 虚线、其余实线；
- 各 builder 顶点数/面数/标签集正确；
- 函数：sin 采样路径连续；tan 在 π/2 处断开（≥2 个 path）；二次函数顶点标注坐标正确；
- nice ticks：range=7 → step=2；range=0.3 → step=0.05 等（Heckbert 对拍）；
- 安全求值：`__import__` / 属性访问 / 非法节点抛 FigureParamsError；
- validate_figure_params 非法输入拒绝；
- 全类型 smoke：render() 返回合法 SVG。

## 8. 交付物清单

| 文件 | 说明 |
|---|---|
| `services/api/app/services/figure_renderer.py` | 渲染核心（约 600 行，零第三方依赖） |
| `services/api/alembic/versions/m2_015_figure_params.py` | DB 迁移 |
| `services/api/app/models/question_bank.py` | +`figure_params` 字段 |
| `services/api/scripts/backfill_figure_params.py` | 批量参数提取+替换脚本 |
| `services/api/tests/test_figure_renderer.py` | 单元测试 |
| `deliverables/figure-renderer/01-github-research.md` | 调研报告 |
| `deliverables/figure-renderer/02-design.md` | 本文档 |
| `deliverables/figure-renderer/03-verification.md` | 验证与对比报告 |

## 9. 分期

- **v1（本次）**：立方体族（正方体/长方体/三棱柱/三棱台）+ 锥体族（四棱锥/三棱锥）+ 球/外接球组合 + 函数图像 + 通用多面体兜底；规则+LLM 混合提取；15 题存量替换验证。
- **v2（后续，不在本次范围）**：圆锥/圆柱/旋转体、空间向量图、截面辅助线、平面几何（圆/相切/弦切角）、角度弧线标注、渲染 SVG→PNG 缩略图服务。
