# F13 可视化讲解 · GitHub 调研报告

> 调研日期：2026-08（本轮）。共深入调研 **16 个重点项目**（覆盖 6 类方向，另有 4 个补充项目）。
> **Star 数说明**：本轮执行环境无法直连 api.github.com（TLS 被阻断），Star 数为 web 搜索快照 /
> star-history 等聚合站近似值，仅供参考，请以仓库页实时数字为准。所有链接均经搜索验证真实。

## 1. 动画引擎与交互式数学平台

### 1.1 Manim Community（[ManimCommunity/manim](https://github.com/ManimCommunity/manim)）
- **Star**：约 20k+（聚合站快照；原 3b1b 版 [3b1b/manim](https://github.com/3b1b/manim) 约 60k+）
- **技术栈/渲染**：Python 场景 → Cairo/OpenGL 离线渲染成视频/图片，非 Web 实时交互。
- **引导式亮点**：`Scene + Mobject + Animation` 三件套——所有图形对象叠加在时间轴上，
  `self.play(FadeIn(axes), Create(curve), Indicate(point))` 声明式分步揭示；
  "一个讲解步骤 = 一个带目标状态的原子动画"。
- **可借鉴**：把讲解建模为「有序步骤序列（timeline of keyframes）」，每步只描述**目标图形状态 +
  过渡类型**，与"AI 只输出结构化参数"完全同构。动画命名（Create/FadeIn/Transform/Indicate）
  可直接作为我们 figure 事件帧语义的词汇表。渲染管线不适合照搬（太重、离线视频）。

### 1.2 Manim Slides（[jeertmans/manim-slides](https://github.com/jeertmans/manim-slides)）
- **Star**：约 1.5k（搜索快照）
- **技术栈/渲染**：Python，Manim 的演示封装：Scene 切成 Slide，支持**上一页/下一页/反向播放**。
- **引导式亮点**：Step-by-step reveal + 可逆导航——每一 Slide 对应一个讲解步骤，可前进、后退、重播。
- **可借鉴**：前端 MathFigure 组件的帧导航模型直接对标（帧圆点 + 上一步/下一步/重播按钮），
  图形帧序列可前可后，正好满足"图形随讲解步骤逐步出现"且学生可回看。

### 1.3 Manim Web（[manim-web/manim-web](https://github.com/manim-web/manim-web)）
- **Star**：约 1k+（搜索快照）
- **技术栈/渲染**：TypeScript 重写 Manim，WebAssembly 跑在浏览器里渲染到 Canvas。
- **引导式亮点**：把 Manim 的声明式动画模型搬到浏览器，可实时播放/暂停/seek，解决"视频不可交互"。
- **可借鉴**：验证了「结构化参数 + 浏览器渲染 + 时间轴动画」在纯 Web 可行的关键路线——
  我们的后端出参数化 SVG、前端负责动效，架构方向与其一致。

### 1.4 MathBox（[unconed/mathbox](https://github.com/unconed/mathbox)）
- **Star**：约 4.5k（搜索快照；底层 [mrdoob/three.js](https://github.com/mrdoob/three.js) 约 103k）
- **技术栈/渲染**：JS/TS + WebGL 自定义 shader；声明式场景图（cartesian/polar/vector field 图元）。
- **引导式亮点**：shader 级插值与时间参数化动画，图元随时间平滑变形/出现/消失，适合华丽动态可视化。
- **可借鉴**：其「关键帧 + 属性补间」抽象可用于未来升级；但 WebGL 属重依赖，与"不引入重依赖"
  冲突——本期只借鉴思想，立体几何仍走我们自研的轴测投影 SVG 线框。

### 1.5 GeoGebra（[geogebra/geogebra](https://github.com/geogebra/geogebra)）
- **Star**：约 4k（搜索快照）
- **技术栈/渲染**：Java/GWT 编译为 HTML5/JS 动态数学套件；官方 Apps API 支持 iframe 嵌入 + 脚本控制。
- **引导式亮点**：**构造步骤（Construction Protocol）+ 导航条**——每一步作图（点→线→圆→交点）按序
  记录，可逐步播放/回退，是"图形随讲解步骤逐步出现"的教科书实现。
- **可借鉴**：「构造协议 = 步骤序列」正是我们的分步渲染模型（帧 = 构造步骤）；
  但闭源核心 + iframe 依赖与"自研确定性 SVG"定位冲突，仅借鉴其步骤导航与 JSON 命令形态。

### 1.6 Motion Canvas（[motion-canvas/motion-canvas](https://github.com/motion-canvas/motion-canvas)）
- **Star**：约 18.6k（star-history 快照）
- **技术栈/渲染**：TypeScript，Canvas 2D；generator 函数 + `yield* tween()` 表达时间轴，编辑器实时预览。
- **引导式亮点**：时间驱动 + 声明式关键帧，动画随代码块逐步推进，可 seek/重播。
- **可借鉴**：「步骤块 + 时间轴」的组件承载模型——SSE 每推送一个步骤块，前端即时渲染并补间，
  对"边生成边显示"的流式体验尤其有启发（我们前端用帧数组 + Transition 实现等价效果，零依赖）。

## 2. AI 数学解题可视化

### 2.1 ChatTutor（[HugeCatLab/ChatTutor](https://github.com/HugeCatLab/ChatTutor)）⭐ 最核心对标
- **Star**：约 1k 级（新项目，快速上升中；搜索快照）
- **技术栈/渲染**：多 Agent + 可视化画布；LLM 输出 **DSL 结构化绘图指令**（函数/几何图形/思维导图），
  前端解析 DSL 逐步绘制——"老师边讲边画边板书"。
- **引导式亮点**：与本任务（F13）目标几乎一致：AI 讲解过程中动态生成图形、图形随讲解逐步出现、
  **AI 只能输出结构化绘图指令而非自由 SVG**。国内已有仿制品（chat-paint 等）验证需求真实。
- **可借鉴**：① 结构化绘图 DSL 的指令形态（图形类型 + 参数 + 分步揭示）；② 画布与对话流并行
  （边讲边画）；③ 其"绘图指令校验后渲染、非法丢弃不阻断讲解"的容错纪律与我们一致。
  差异：我们的渲染放在**后端确定性 SVG**（可校验、可断言），它偏前端绘制。

### 2.2 AlphaGeometry（[google-deepmind/alphageometry](https://github.com/google-deepmind/alphageometry)）
- **Star**：约 4k+（搜索快照；alphageometry2 后续发布）
- **技术栈/渲染**：符号推理引擎（DD+AR）+ LLM 提出几何构造建议；输出形式化证明，不渲染图形。
- **引导式亮点**：LLM 输出**受限于形式化语言的构造指令**，被确定性引擎校验——"AI 提建议、引擎裁决"。
- **可借鉴**：**LLM 生成 + 确定性引擎校验**的闭环范式，正是我们的架构：
  LLM 输出 figure_params → `validate_figure_params` 校验 → 非法即反馈重试/丢弃。
  其"构造可被形式化检查"证明"图形参数可被程序断言"是成熟做法。

### 2.3 manim_gpt（[Ambier/manim_gpt](https://github.com/Ambier/manim_gpt)）
- **Star**：数百级（搜索快照）
- **技术栈/渲染**：自然语言/语音 → LLM 生成 Manim Python 代码 → Manim 渲染动画视频。
- **引导式亮点**：全链路 LLM 生成动画，但生成物是**自由代码**（可执行任意内容，需沙箱）。
- **可借鉴**：反例参考——LLM 自由生成渲染代码的做法不满足我们"确定性、可校验、禁止自由 SVG"约束，
  佐证我们选参数化 JSON 而非代码生成的正确性。

### 2.4 Geogebra-WebChat（[liangdabiao/Geogebra-WebChat](https://github.com/liangdabiao/Geogebra-WebChat)）
- **Star**：数百级（搜索快照）
- **技术栈/渲染**：聊天 + AI + GeoGebra 画图：LLM 把自然语言转成 GeoGebra 结构化命令再执行绘图。
- **引导式亮点**：**一句话搞定几何绘图**的最小闭环（chat → AI → 结构化命令 → 画图），证明
  "LLM 输出结构化绘图指令"在轻量 Web 应用中的可行性。
- **可借鉴**：最小闭环的链路划分（自然语言 → 指令提取 → 渲染），与我们 planner 角色对应；
  但依赖 GeoGebra 重运行时，我们以自研 SVG 替代。

### 2.5 ToRA（[microsoft/ToRA](https://github.com/microsoft/ToRA)）
- **Star**：约 2k+（搜索快照）
- **技术栈/渲染**：工具集成推理（LLM + 符号计算工具），数学解题通过结构化工具调用闭环，非图形。
- **引导式亮点**：输出受**工具调用 schema** 约束，工具结果回填修正——与 socratic_solver 现有 TIR 机制同构。
- **可借鉴**：图形指令应作为**受 schema 约束的"工具调用"**来设计（我们已用 pydantic 契约校验实现同效），
  而非自由文本；同时佐证"结构化输出 + 执行回填"是 AI 数学的主流范式。

## 3. 函数图像动态绘制

### 3.1 function-plot（[mauriciopoppe/function-plot](https://github.com/mauriciopoppe/function-plot)）
- **Star**：约 1.1k（搜索快照）
- **技术栈/渲染**：基于 d3 的 SVG 绘图；**声明式配置对象** `{target, data:[{fn,color,graphType}], xAxis, yAxis, grid}`；
  Web Worker 采样，支持求导/积分/渐近线、`duration/animate` 过渡动画。
- **引导式亮点**：纯数据驱动——改 JSON 即重渲染；内置过渡动画参数可做"曲线逐步画出"。
- **可借鉴**：与我们的 figure_renderer（JSON → 确定性 SVG）高度同构；其 data[] + graphType +
  采样策略的图模型、以及"动画/时长"参数证明"曲线随步骤画出"可行。我们的 figure_renderer
  已参考其 sampler 与 d3-scale tickIncrement，本阶段沿用并扩展分步帧。

### 3.2 mafs（[stevenpetryk/mafs](https://github.com/stevenpetryk/mafs)）
- **Star**：约 4.7k（搜索快照）
- **技术栈/渲染**：React 组件库，SVG（viewbox + path），动画基于 motion；
  **composable API**：`<Mafs><Coordinates/><Plot.OfX/><Point/></Mafs>`。
- **引导式亮点**：一个数学对象 = 一个组件，声明式叠加；进入/退出动画内建；
  Khan Academy 的 Perseus 已采用 mafs 做交互图（"Create Angle Mafs Graph" PR）。
- **可借鉴**：思想可直接移植 Vue3——"坐标系组件/曲线组件/标注组件"按步骤 `v-if` + `<Transition>`
  增量挂载；其"数学对象 = 组件 + 可动画属性"抽象指导我们 MathFigure 的帧结构（零依赖实现）。

### 3.3 d3（[d3/d3](https://github.com/d3/d3)）
- **Star**：约 108k（搜索快照）
- **技术栈/渲染**：数据绑定（data join）底层库，产出 SVG path / Canvas；
  `d3-scale` 坐标映射、`d3-shape` 插值、`d3-transition` 动画。
- **引导式亮点**：**enter/update/exit + transition** 是"数据 diff → 视觉增量揭示"的教科书范式，
  可编排"先画轴 → 再画线 → 再画点"的时间轴。
- **可借鉴**：增量揭示范式指导我们 figure 事件与帧序列的语义（帧 N+1 = 帧 N + 新增要素）；
  渲染侧 figure_renderer 已借鉴其 nice ticks（tickIncrement）。

### 3.4 plotly.js（[plotly/plotly.js](https://github.com/plotly/plotly.js)）
- **Star**：约 17k（搜索快照）
- **技术栈/渲染**：SVG + WebGL 双栈；**声明式 JSON 图模型** `{data, layout, frames}`。
- **引导式亮点**：完全 JSON 驱动；`frames` + animation 原生分步动画（slider/play）——"曲线随时间逐段出现"。
- **可借鉴**：其 frames 机制是"分步揭示"的现成协议范式（一帧 = 一步），我们的 figure 事件
  载荷直接对标；但 min ~3MB 属重依赖，**只借鉴协议设计，不引入**。

## 4. 立体几何 Web 渲染

### 4.1 JSXGraph（[jsxgraph/jsxgraph](https://github.com/jsxgraph/jsxgraph)）⭐ 与我们最同源
- **Star**：约 1.1k（搜索快照）
- **技术栈/渲染**：纯 JS，SVG/Canvas/VML 三后端；**几何"构造"式 API**
  （`board.create('point',...)`, `create('functiongraph', f)`）+ 约束求解 + 实验性 3D。
- **引导式亮点**：元素依赖关系（交点/轨迹联动）、`suspendUpdate/resumeUpdate` 支持
  "批量构建后分步揭示"；layers 显隐控制。教育界广泛采用（Moodle 插件）。
- **可借鉴**：与 figure_renderer 同为"参数/构造 → SVG"，天然同源；其 Board 元素模型 +
  分层显示 + 分步更新，指导我们"帧 = 元素子集 + 显隐"的派生逻辑。体积 ~100KB 也不算重，
  但本期不引入——自研渲染器已覆盖所需几何体。

### 4.2 geometric（[HarryStevens/geometric](https://github.com/HarryStevens/geometric)）
- **Star**：约 460（搜索快照）
- **技术栈/渲染**：纯几何**计算**库（不渲染）：点/线/圆/多边形的交点、距离、角度、旋转、平移。
- **引导式亮点**：计算与渲染彻底分离——几何运算封装成确定性纯函数。
- **可借鉴**：为 figure_renderer 未来扩展（切线/法线/交点等解析几何构造）提供"纯计算层 +
  渲染层分离"的参考架构，与"确定性、可校验"目标天然契合。

## 5. 引导式学习系统

### 5.1 Khan Academy Perseus（[Khan/perseus](https://github.com/Khan/perseus)）
- **Star**：约 2.4k（搜索快照；旧版 khan-exercises 已归档）
- **技术栈/渲染**：题目编辑器 + 渲染器 widget 体系（interactive-graph / number-line 等），
  已采用 mafs 做交互图；JSON 题目 schema + 数据驱动校验。
- **引导式亮点**：**hint 分级**——每道题挂多级 hint 逐级更具体，最后一级几乎给答案，按需展开；
  题目/图形/判分全部数据驱动可复现。
- **可借鉴**：hint 分级与我们的提示阶梯（Point→Teach→Bottom-out）同构——**图形帧数随提示级别
  递增**是本功能的防泄题核心设计（第 1 帧只给构图，标注帧仅在答对/揭示时出现），直接对标其
  "逐级揭示"教学法。

### 5.2 Mathigon（[mathigon/textbooks](https://github.com/mathigon/textbooks)）
- **Star**：约 700（搜索快照）
- **技术栈/渲染**：自研交互组件（几何画板/函数绘图），Markdown + 组件语法写课程。
- **引导式亮点**：**"课程即逐步揭示"**——step / blank / reveal 块滚动或点击逐步展开，
  图形随文本同步出现，交互组件内嵌讲解流。
- **可借鉴**：其"文字 - 图形 - 交互编排成单条引导流"的产品形态正是我们 figure 事件与
  token 流交织的目标；step/reveal 块结构映射为 SSE 事件序列。

### 5.3 reveal.js（[hakimel/reveal.js](https://github.com/hakimel/reveal.js)）
- **Star**：约 68k（搜索快照）
- **技术栈/渲染**：纯前端演示框架；**fragments** 机制让同页元素按声明顺序逐步出现，事件钩子可编程。
- **引导式亮点**：渐进式揭示的最经典原语（fade/zoom 按序进入），讲稿与画面同步。
- **可借鉴**：fragments 的"声明式揭示顺序 + 事件钩子"直接翻译为 Vue3 `<Transition>` + 帧索引状态；
  Auto-Animate 的步骤间补间参考做图形渐变。

## 6. 其他补充（简短）

| 项目 | 链接 | 要点 |
|---|---|---|
| CindyJS | [CindyJS/CindyJS](https://github.com/CindyJS/CindyJS) | WebGL+SVG 动态几何；Cindy3D/CindyGL 供真 3D 曲面参考 |
| observablehq/plot | [observablehq/plot](https://github.com/observablehq/plot) | 声明式 marks 图语法，服务端化 SVG 输出思路 |
| KaTeX | [KaTeX/KaTeX](https://github.com/KaTeX/KaTeX) | 讲解文本公式渲染底座，与 SVG 图形互补 |
| khayyam-math | [khayyam-math/khayyam-math](https://github.com/khayyam-math/khayyam-math) | 多工具图形路由 + 视觉审计（搜索快照，数百 star） |
| Desmos API | [desmos.com/api](https://www.desmos.com/api/v1.12/docs/) | 非开源；graph state 序列化回放思路，iframe 依赖不采用 |

## 对比总结

| 项目 | 渲染技术 | 交互性 | 声明式/命令式 | 分步动画 | 对我们适配度 |
|---|---|---|---|---|---|
| Manim (Community) | Python→Cairo/OpenGL 视频 | 弱 | 命令式场景 | 强（Scene/Animation） | 中：分步思想，管线不可搬 |
| manim-slides | 视频封装 | 导航/回放 | 命令式 | 强（可逆步骤） | 高：帧导航模型 |
| manim-web | WASM+Canvas | 强 | 声明式 | 强 | 高：验证 Web 路线 |
| MathBox | WebGL shader | 中 | 声明式 | 强（时间补间） | 中：思想借鉴，依赖重 |
| GeoGebra | HTML5/JS | 强 | 构造协议 | 强（步骤导航） | 高：构造协议=帧序列 |
| Motion Canvas | Canvas 2D | 中 | generator 时间轴 | 强 | 高：流式分步编排 |
| **ChatTutor** | 前端 DSL 画布 | 强 | 结构化 DSL | 强（边讲边画） | **最高：同目标同约束** |
| AlphaGeometry | 符号引擎（无渲染） | 无 | 形式化指令 | 无 | 高：LLM生成+引擎校验闭环 |
| manim_gpt | Manim 代码 | 弱 | 自由代码 | 强 | 低：反例（自由代码不可校验） |
| Geogebra-WebChat | GeoGebra 命令 | 强 | 结构化命令 | 中 | 高：最小闭环链路 |
| ToRA | 工具调用 | 无 | schema 约束 | 无 | 高：指令即工具调用 |
| function-plot | SVG(d3) | 缩放/tips | 声明式 data[] | 中 | 高：JSON→SVG 同构 |
| mafs | SVG | 强 | 组件式 | 强 | 高：组件化抽象 |
| d3 | SVG/Canvas | 中 | data join | 强 | 高：enter/update/exit 范式 |
| plotly.js | SVG+WebGL | 强 | JSON+frames | 强 | 中：协议借鉴，依赖重 |
| JSXGraph | SVG/Canvas | 强 | 构造式 | 强 | **高：同源 SVG + 分步揭示** |
| geometric | 纯计算 | 无 | 纯函数 | 无 | 高：计算/渲染分离 |
| Perseus | SVG+mafs | 强 | JSON widget | 中（hint 分级） | 高：hint 分级揭示 |
| Mathigon | 自研组件 | 强 | step/reveal | 强 | 高：文字图形编排 |
| reveal.js | DOM/CSS | 弱 | fragments | 强 | 高：渐进揭示原语 |

## 对本项目的落地结论

1. **分步揭示模型**（Manim Scene/Animation + GeoGebra 构造协议 + manim-slides 可逆步骤）：
   图形 = **有序帧序列**，每帧 = 一份完整可渲染的 figure_params（后帧在前帧上增加要素），
   前端帧导航（上一步/下一步/重播）对标 manim-slides。
2. **AI 触发与约束**（ChatTutor DSL + AlphaGeometry + ToRA）：AI 只输出**结构化图形指令**
   （figure_params），经 `validate_figure_params` 确定性校验，非法反馈重试或丢弃，
   **绝不自由生成 SVG**——沿用并强化现有 figure_renderer 纪律。
3. **防泄题的逐级揭示**（Perseus hint 分级）：图形帧数随提示级别（Point→Teach→Bottom-out）递增，
   答案性标注（零点/极值点/交点/顶点字母）只在答对确认与揭示总结时出现。
4. **前端零重依赖**：借鉴 mafs 组件化 + reveal.js fragments + d3 enter/update/exit 思想，
   用 Vue3 `<Transition>` + 帧索引状态实现渐进动画，不引入 plotly/three.js/JSXGraph。
5. **协议向后兼容**：figure 事件为新增事件类型，旧前端按"未知事件忽略"铁律自然兼容；
   旧数据无 figure 块，新前端优雅降级。
