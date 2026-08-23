# 智学数研 M4 科研端 · 开发前准备包 v2.0

> 更新时间：2026-08-21  
> 产品方案：任务流驱动的研究工作台（方案 A）  
> 当前阶段：需求、架构、接口和高保真原型已统一；后续开发以本目录为单一入口。

## 1. 我们要做什么

科研端不是学生端或教师端换皮，也不是一组 AI 工具按钮。它围绕“研究项目”组织文献、数学验证、Lean4 形式化、论文写作、论文初审、教育研究和三端成果回流。用户可以从研究问题开始，一直走到带来源、运行记录和版本信息的论文证据。

核心原则：

- **证据先行**：结论必须能追到来源、输入、执行器、版本和日志。
- **终审在人**：AI 只给建议、提取或草案，不判断创新性、排名和录用。
- **状态诚实**：未能验证、外部源不可用、离线和执行失败分别表达。
- **可重复运行**：文献解析、公式验证、Lean 构建、LaTeX 编译、统计图表都产生 Run。
- **数据可迁移**：支持 RIS、BibTeX、CSL JSON、TEX、CSV、JSON 和复现包。

## 2. 本目录交付物

| 文件 | 用途 |
|---|---|
| [M4_科研端详细需求分析.md](./M4_科研端详细需求分析.md) | 产品定位、调研、用户任务、IA、底层方案、正常/降级矩阵和验收指标 |
| [M4_API接口文档.md](./M4_API接口文档.md) | `/api/research/v2` 字段级契约、状态机、错误、SSE、权限和工作流适配 |
| [M4_科研端实施计划.md](./M4_科研端实施计划.md) | 开发前文档与原型的任务、文件、测试和验收步骤 |
| [apifox/m4_api_openapi_v2.0.json](./apifox/m4_api_openapi_v2.0.json) | 可导入 Apifox 的 OpenAPI 3.1 核心接口 |
| [prototype/index.html](./prototype/index.html) | 可交互高保真科研端原型入口 |
| [prototype/PROTOTYPE_QA.md](./prototype/PROTOTYPE_QA.md) | 多视口、交互、降级和视觉验收记录 |

旧 `apifox/m4_api_openapi_v1.0.json` 仅保留为历史参考，不再作为开发契约。

## 3. 页面地图

| 路由 | 页面 | 主要任务 |
|---|---|---|
| `/research` | 研究驾驶舱 | 项目、待确认、运行、跨端任务和研究进度 |
| `/research/projects/:id` | 项目空间 | 问题、任务、资产、证据账本、活动与复现包 |
| `/research/literature` | 文献桌面 | 检索、纳入/排除、PDF、笔记、引用核验和研究脉络 |
| `/research/verify` | 数学验证台 | 假设确认、五能力、四态证据和升级 Lean |
| `/research/formalize` | Lean4 形式化台 | statement、文件、目标、诊断、构建、缓存和取消 |
| `/research/writing/:id` | LaTeX 论文工作台 | 编辑、PDF、SyncTeX、引用、润色、编译和导出 |
| `/research/review` | 初审批次 | 五层检查、批量进度、人工关注和证据报告 |
| `/research/education` | 教育研究台 | 匿名数据、隐私预检、统计图表和写入论文 |
| `/research/runs` | 运行中心 | 所有任务的模式、进度、日志、重试、取消和复现 |

全局使用“顶部项目栏 + 左侧任务导航 + 中央工作区 + 右侧证据栏 + 底部运行抽屉”。沉浸式 Lean/LaTeX 页面可折叠证据栏，保留运行抽屉。

## 4. Lean4 已锁定的实现方式

Lean4 是一期正式后端能力：

1. Web 端只负责源码编辑、statement 确认、目标与诊断展示。
2. 后端 formal worker 使用固定 Lean toolchain、Mathlib commit 和镜像摘要。
3. Mathlib 预编译缓存只读挂载，用户项目按导入闭包增量构建。
4. 每次 check/build/tactic 都有独立 run、墙钟/CPU/内存限制和进程树取消。
5. 只有 Lean kernel 接受且满足项目的 `sorry/admit` 策略时才显示“形式化已验证”。
6. 浏览器离线时允许编辑、模板和导出项目，但结果固定为 `formal_pending`。

## 5. 正常运行与降级

| 模式 | 含义 | 典型能力 |
|---|---|---|
| `FULL` | 后端、必要外部源与星辰工作流可用 | 多源检索、工作流增强、全部确定性执行器 |
| `LOCAL_ENGINE` | 后端可用，外部 API 或星辰不可用 | GROBID/Docling、SymPy、Lean4、Tectonic、本地索引/规则 |
| `BROWSER_LOCAL` | 后端不可达 | IndexedDB、PDF.js 基础解析、CSL、BM25/筛选、轻量公式抽样、图表和离线队列 |
| `UNAVAILABLE` | 当前没有可信执行器 | 保存草案或导出运行包，不生成伪结果 |

每个结果必须返回或保存：

```json
{
  "resolved_mode": "local_engine",
  "capabilities_used": ["backend", "sympy"],
  "missing_capabilities": ["workflow", "openalex"]
}
```

恢复完整模式后不自动重跑昂贵或敏感任务，先提示用户“升级重跑”；旧 run 保留用于比较。

## 6. 星辰工作流边界

科研业务只依赖统一 `WorkflowAdapter`，不直接读取星辰内部节点字段。队友已经完成的工作流通过注册表提供 `workflow_key`、版本、schema、超时和回调签名。

适合星辰增强：翻译、论文结构提取、语言建议、自然语言形式化草案、科研助手编排。

必须由确定性/本地系统完成：引用真伪核验、SymPy 判定、Lean kernel、Tectonic 编译结果、隐私阈值与权限判断。

星辰不可用时路由到本地规则或本地模型；没有本地生成模型时只返回规则检查或检索证据，不冒充生成结果。

## 7. 底层组件建议

| 领域 | 推荐实现 |
|---|---|
| 文档解析 | GROBID（学术结构/引用）+ Docling（多格式/表格）→ DocumentIR |
| 文献元数据 | Crossref + OpenAlex + Semantic Scholar，带缓存、熔断和来源记录 |
| 本地检索 | BM25/Tantivy 或现有搜索服务；向量检索作为增强 |
| 数学验证 | SymPy + 量纲规则 + 受约束反例搜索 |
| 形式化 | Lean4 + Mathlib + 受控 REPL/LeanDojo 风格适配器 |
| 排版 | Pandoc AST 转换 + Tectonic 固定 bundle + SyncTeX |
| 任务 | Run Orchestrator + 轻/文档/计算/形式化/工作流队列 |
| 数据 | PostgreSQL + 对象存储 + Redis/队列 + 搜索索引 |
| 浏览器本地 | IndexedDB、PDF.js、CSL、DuckDB-Wasm/Arquero、Vega-Lite/ECharts |

## 8. 三端联动

- 学生端推导发布为 `VerificationCase` 副本，科研端不直接修改学生原记录。
- 教师端 F12 与科研端初审共用引擎，但评委/作者字段由后端权限裁剪。
- 教师发布 `ResearchBrief`，授权后创建科研项目。
- 教育数据通过匿名 `LearningDatasetProduct` 快照进入科研端；聚合切片 k≥20。
- 研究证据经审批可发布到教师题库/方法库；消费端保存来源版本。
- 源资产撤回或过期时通知消费端，不静默删除已使用内容。

## 9. 开发顺序

1. Project、Run、Evidence、Capability 和 AuthZ 基础模型。
2. 运行中心与执行路由，再接各领域 worker。
3. 文献桌面、数学验证和 Lean4 后端。
4. LaTeX 工作台、初审和教育研究。
5. 星辰增强、科研助手和三端发布审批。
6. 金标准集、降级演练、压力测试与安全审计。

不要先制作十个独立页面再补任务模型；所有长任务从第一天统一走 Run。

## 10. 原型使用

直接打开 `prototype/index.html`，或在 `prototype` 目录启动任意静态服务器。推荐浏览器视口 1440×900。原型顶部可以切换 FULL、本地引擎和浏览器离线，观察按钮、结果、能力说明与运行抽屉如何变化。

原型不是后端实现，但交互、信息架构、状态语义和接口字段必须与 v2 文档保持一致。

## 11. 统一术语

| 术语 | 含义 |
|---|---|
| Project | 研究问题、资产、任务、运行与证据的容器 |
| Run | 一次不可变执行记录；重试创建新 run |
| Evidence | 带来源范围、输入哈希和执行器版本的证据 |
| Capability | 当前路径可提供的能力声明 |
| resolved_mode | 实际执行模式，不等于用户期望模式 |
| formal_pending | 尚未完成可信形式化构建或 statement 仍待确认 |
| 人工关注 | 初审事实性问题的处理优先级，不是论文排名 |

