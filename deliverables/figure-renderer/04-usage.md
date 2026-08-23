# 参数化配图渲染系统 — 使用说明

## 1. 快速开始

```bash
cd services/api

# 运行渲染器单元测试（63 个用例）
.venv\Scripts\python.exe -m pytest tests\test_figure_renderer.py -q

# 批量回填（规则优先 + LLM 兜底）：
.venv\Scripts\python.exe -m scripts.backfill_figure_params --dry-run --limit 20      # 预演
.venv\Scripts\python.exe -m scripts.backfill_figure_params --method auto             # 正式
.venv\Scripts\python.exe -m scripts.backfill_figure_params --method llm --limit 5    # 仅 LLM
.venv\Scripts\python.exe -m scripts.backfill_figure_params --only-missing --limit 10 # 补无图题
```

## 2. 代码调用

```python
from app.services.figure_renderer import render_figure, validate_figure_params, to_data_uri, check_svg_invariants

fig = {
    "version": 1,
    "type": "quad_pyramid",           # 四棱锥 P-ABCD
    "params": {"base_w": 4, "base_d": 4, "height": 2.8},
    # "view": {"mode": "axonometric", "yaw": -28, "elev": 30},  # 可选真透视
    "size": [400, 300],
}
svg = render_figure(fig)              # -> SVG 字符串（确定性）
uri = to_data_uri(svg)                # -> data:image/svg+xml;base64,...
problems = check_svg_invariants(fig, svg)  # -> [] 即通过
```

支持的 `type`：`cube`（正方体）、`cuboid`（长方体）、`triangular_prism`（三棱柱）、
`quad_pyramid`（四棱锥）、`tri_pyramid`（三棱锥）、`tri_frustum`（三棱台）、
`sphere`（球/外接球，可内接几何体）、`polyhedron`（通用多面体）、
`function`（函数图像）、`triangle2d`（平面三角形）。

完整参数结构见模块内 `FIGURE_SCHEMA_DOC`（LLM 提取 prompt 也复用它，单一事实来源）。

## 3. 渲染原理（保证正确性的关键）

1. **默认斜二测投影**（人教版教材画法）：`屏幕 = (x + 0.3536y, −z − 0.3536y)`，
   顶点恒在底面上方；可选 `view.mode=axonometric`（Rz∘Rx 轴测正交投影+可选透视，
   锥体会自动二分抬升仰角直至顶点露出底面）。
2. **隐藏线**：凸多面体面法线 backface culling（面顶点序自动归一为外法向），
   所有相邻面均背向观察者的边画虚线（`stroke-dasharray`）。锥体底面按教材惯例
   设为恒可见面。
3. **锥体不变量**：渲染时强制断言顶点屏幕 y 严格小于底面所有顶点 y，违例直接抛
   `FigureParamsError`——从机制上杜绝"顶点 P 画在底面内部"。
4. **函数图像**：AST 白名单安全求值（无 eval/exec）+ 递归中点自适应采样 +
   渐近线断开（异号且超出视口 4 倍判为断点）+ Heckbert nice 刻度。

## 4. 批量回填流程（每题）

```
规则提取（内置高考真题模板，零 LLM）
   ↓ 未命中
LLM 提取（DeepSeek，prompt = FIGURE_SCHEMA_DOC + 题干，只输出 JSON）
   ↓
validate_figure_params() 参数校验（失败 → 带错误信息重试 1 次）
   ↓
render_figure() 代码渲染（失败 → 放弃，保留原图）
   ↓
check_svg_invariants() 几何不变量（fatal → 放弃，保留原图）
   ↓ 全部通过
写库：figure_params=参数 JSON；image[0]=新 data URI；annotate_meta.figure_gen 记录
```

**失败安全**：任何一步失败都保留原图，绝不覆盖成坏图。

## 5. 扩展新图形类型

1. 在 `figure_renderer.py` 写 `_poly_xxx(...) -> Polyhedron`（顶点表+面表，法向自动归一）；
2. `_validate_solid` 增加该类型的参数校验分支；
3. `_build_scene` 增加构建分支；`_SUPPORTED_TYPES` 注册；
4. `FIGURE_SCHEMA_DOC` 补充一段 schema 说明（LLM 自动学会提取）；
5. `tests/test_figure_renderer.py` 增加隐藏边断言 + smoke 用例。

## 6. 文件清单

| 文件 | 说明 |
|---|---|
| `app/services/figure_renderer.py` | 渲染核心（纯标准库，约 1100 行） |
| `app/models/question_bank.py` | +`figure_params` JSONB 字段 |
| `alembic/versions/m2_015_figure_params.py` | 迁移（已执行） |
| `scripts/backfill_figure_params.py` | 批量提取/渲染/替换脚本 |
| `tests/test_figure_renderer.py` | 63 个单元测试 |
| `deliverables/figure-renderer/01-github-research.md` | GitHub 调研报告 |
| `deliverables/figure-renderer/02-design.md` | 方案设计 |
| `deliverables/figure-renderer/03-verification.md` | 验证与对比报告 |
