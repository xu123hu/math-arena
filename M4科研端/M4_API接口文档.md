# 智学数研 M4 科研端 API 接口文档 v2.0

> 日期：2026-08-21｜Base path：`/api/research/v2`  
> 适用：Web 科研端、学生/教师端联动、Research API、worker 与星辰 WorkflowAdapter。  
> 目标：统一项目、运行、证据、能力、完整/降级和 Lean4 后端构建契约。

---

# 0. 通用约定

## 0.1 鉴权与角色

使用平台 JWT：`Authorization: Bearer <token>`。科研端允许 `researcher` 和被授权的 `teacher`；跨端发布另检查对象级 policy。前端隐藏按钮不是权限控制，后端必须裁剪不可见字段。

角色：`student / teacher / researcher / reviewer / platform_admin`。

## 0.2 信封

成功：

```json
{
  "success": true,
  "data": {},
  "meta": {"request_id":"req_01...","trace_id":"tr_01...","server_time":"2026-08-21T06:00:00Z"}
}
```

失败：

```json
{
  "success": false,
  "error": {
    "code": "LEAN_TIMED_OUT",
    "message": "Lean 构建超过资源预算",
    "retryable": true,
    "details": {"run_id":"run_01...","limit_seconds":90}
  },
  "meta": {"request_id":"req_01...","trace_id":"tr_01..."}
}
```

## 0.3 ID、时间、分页与版本

- ID 使用带前缀 ULID：`prj_ / run_ / evd_ / doc_ / ver_ / frm_ / man_ / rev_ / dss_ / pub_`。
- 时间为 UTC RFC 3339；前端按用户时区显示。
- 列表采用游标：`?limit=20&cursor=...`；`limit` 范围 1–100。
- 可编辑对象含整数 `version`；更新使用 `If-Match: "<version>"`，冲突返回 `409 VERSION_CONFLICT`。

## 0.4 幂等

创建项目、run、证据版本、发布和导出必须带 `Idempotency-Key`。服务端至少保存 24 小时；相同 key 不同 body 返回 `409 IDEMPOTENCY_CONFLICT`。

## 0.5 运行模式

枚举：

```text
requested_mode: auto | full | local_engine | browser_local
resolved_mode: full | local_engine | browser_local | unavailable
```

服务端不会返回 `browser_local` 执行结果；浏览器离线结果在同步时作为 `client_run` 上传。所有结果对象必须含：

```json
{
  "resolved_mode":"local_engine",
  "capabilities_used":["backend","sympy"],
  "missing_capabilities":["workflow","openalex"],
  "degraded_reasons":[{"capability":"openalex","reason":"circuit_open"}]
}
```

## 0.6 Run 状态机

```text
queued → preparing → running → awaiting_confirm → running → succeeded
                  ↘ cancelling → cancelled
                  ↘ failed | timed_out | out_of_memory | infra_error
```

Lean 可使用更细阶段 `elaborating`，在 API 中放入 `phase`，不扩展顶层 status。

`succeeded` 只表示执行器完成其契约；具体业务 verdict 另存。例如 Lean 构建 run 成功后 proof verdict 才可能是 `verified`。

## 0.7 SSE

`GET /runs/{run_id}/events`，请求头 `Accept: text/event-stream`；断线重连带 `Last-Event-ID`。

```text
id: evt_01J...
event: progress
data: {"run_id":"run_01...","status":"running","phase":"elaborating","progress":64,"message":"正在检查 theorem main"}
```

事件类型：`snapshot / progress / log / diagnostic / artifact / awaiting_confirm / completed / failed / heartbeat`。

## 0.8 通用错误

| HTTP | code | 含义 |
|---|---|---|
| 400 | `VALIDATION_ERROR` | 参数或状态不合法 |
| 401 | `UNAUTHENTICATED` | 未登录/令牌失效 |
| 403 | `FORBIDDEN` | 角色或对象权限不足 |
| 404 | `NOT_FOUND` | 对象不存在或不可见 |
| 409 | `VERSION_CONFLICT` | 乐观锁冲突 |
| 409 | `INVALID_STATE_TRANSITION` | 状态不允许当前动作 |
| 413 | `PAYLOAD_TOO_LARGE` | 文件/批次超限 |
| 422 | `STATEMENT_CONFIRM_REQUIRED` | Lean statement 未确认 |
| 422 | `PRIVACY_THRESHOLD_NOT_MET` | 教育数据 k<20 |
| 429 | `QUOTA_EXCEEDED` | 配额不足 |
| 503 | `CAPABILITY_UNAVAILABLE` | 没有可信执行器 |
| 503 | `EXTERNAL_SOURCE_UNAVAILABLE` | 文献源/工作流不可用 |

# 1. 能力与运行中心

## 1.1 GET `/capabilities`

返回服务能力、健康、版本与推荐模式。能力探测可缓存 30 秒。

```json
{
  "success":true,
  "data":{
    "recommended_mode":"full",
    "capabilities":[
      {"key":"lean","available":true,"provider":"local","version":"toolchain-locked","health":"healthy"},
      {"key":"workflow.translate","available":false,"provider":"xingchen","health":"circuit_open"},
      {"key":"sympy","available":true,"provider":"local","version":"locked","health":"healthy"}
    ],
    "limits":{"max_upload_mb":100,"max_review_batch":50,"education_min_k":20}
  },
  "meta":{"request_id":"req_01","trace_id":"tr_01","server_time":"2026-08-21T06:00:00Z"}
}
```

## 1.2 GET `/runs/{run_id}`

```json
{
  "success":true,
  "data":{
    "run_id":"run_01J...","project_id":"prj_01J...","kind":"lean.build",
    "status":"running","phase":"elaborating","progress":64,
    "requested_mode":"auto","resolved_mode":"local_engine",
    "input_hash":"sha256:...","parent_run_id":null,
    "executor":{"name":"lean4","version":"locked","image_digest":"sha256:..."},
    "capabilities_used":["backend","lean","mathlib_cache"],
    "missing_capabilities":[],"degraded_reasons":[],
    "started_at":"2026-08-21T06:01:00Z","finished_at":null,
    "resource_usage":{"cpu_ms":8120,"peak_memory_mb":634},
    "trace_id":"tr_01J..."
  },"meta":{"request_id":"req_01","trace_id":"tr_01J...","server_time":"2026-08-21T06:01:10Z"}
}
```

## 1.3 GET `/runs`

过滤：`project_id`、`kind`、`status`、`resolved_mode`、`created_after`。

## 1.4 POST `/runs/{run_id}/cancel`

仅 queued/preparing/running/awaiting_confirm 可取消。返回 run 快照；重复取消幂等。

## 1.5 POST `/runs/{run_id}/retry`

Body：`{"requested_mode":"auto","reason":"user_retry"}`。创建新 run，`parent_run_id` 指向原 run。

## 1.6 POST `/client-runs/sync`

同步浏览器离线执行记录与操作队列。服务端保留 `resolved_mode=browser_local`，校验 `client_id/input_hash/executor`，不得把客户端声明升级为后端 verified。

# 2. 项目与证据账本

## 2.1 POST `/projects`

```json
{"title":"图神经网络在路径规划中的建模研究","research_question":"在相同约束下，GNN 启发式是否降低搜索节点数？","domain":"mathematical_modeling","stage":"discovery","visibility":"private"}
```

## 2.2 GET `/projects`、GET `/projects/{project_id}`、PATCH `/projects/{project_id}`

详情含统计、成员、最近资产、最近 run 和证据计数；正文资产通过独立接口分页，不在详情一次返回。

## 2.3 GET `/projects/{project_id}/activity`

追加式活动流，支持 `after_event_id`。

## 2.4 POST `/projects/{project_id}/evidence`

```json
{
  "type":"formal_proof",
  "title":"代价函数下界已形式化验证",
  "source":{"object_type":"formal_project","object_id":"frm_01J...","version":4},
  "locator":{"file":"Main.lean","range":{"start_line":12,"start_column":1,"end_line":18,"end_column":8}},
  "run_id":"run_01J...","input_hash":"sha256:...",
  "trust_level":"deterministic_verified"
}
```

Evidence 只追加版本。`trust_level`：`source_observation / rule_checked / numeric_sampled / symbolic_verified / deterministic_verified / ai_suggestion / user_asserted`。

## 2.5 POST `/evidence/{evidence_id}/supersede`

Body：`{"replacement_evidence_id":"evd_...","reason":"假设范围修正"}`。

## 2.6 POST `/evidence/{evidence_id}/retract`

Body 必须含 reason；通知所有 PublicationLink 消费端。

## 2.7 POST `/projects/{project_id}/reproducibility-packages`

异步生成 manifest、参数、环境锁、代码、数据字典、证据索引、许可证和校验和；返回 run。

# 3. 文献、PDF 与知识库

## 3.1 POST `/literature/search`

```json
{
  "project_id":"prj_01J...","query":"graph neural network path planning heuristic",
  "filters":{"year_from":2021,"year_to":2026,"has_full_text":true},
  "sources":["crossref","openalex","semantic_scholar"],"requested_mode":"auto","limit":20
}
```

返回同步第一页；外部源慢时可返回 `search_id` 和 run。每条含 `source_records[]`、去重理由、核验状态和模式信息。

核验状态：`verified_exact / verified_fuzzy / conflicting / not_found / source_unavailable / local_only`。

## 3.2 POST `/literature/collections`、POST `/literature/collections/{id}/items`

加入项目集合时记录 `decision=included|excluded|maybe` 与 `reason`；excluded 不物理删除。

## 3.3 POST `/documents/imports`

multipart：`file`、`project_id`、`parser_preference=auto|grobid|docling`、`requested_mode`。返回 `document.import` run。

## 3.4 GET `/documents/{document_id}`

返回题录、解析状态、页数、IR 版本和可用 artifact；全文 block 分页获取。

## 3.5 GET `/documents/{document_id}/blocks`

过滤 page/section/type；每 block 有 `block_id/page_no/bbox/text/offset/parser_version/confidence`。

## 3.6 POST `/citations/verify`

最多 100 条，异步；逐条返回来源、匹配字段、冲突和状态。缺失源记 `source_unavailable`，不得折算 `not_found`。

## 3.7 POST `/citations/format`

Body：`{"items":[CSL_JSON],"style":"china-national-standard-gb-t-7714-2015-numeric","locale":"zh-CN","output":"text|html|bibtex"}`。此接口可由浏览器 Citation.js 等价实现。

## 3.8 POST `/knowledge/search`

项目/个人库混合检索。无生成模型时 `answer=null`，仍返回 evidence spans；前端显示“仅检索”。

# 4. 数学验证

## 4.1 POST `/verifications`

```json
{
  "project_id":"prj_01J...","source":{"type":"manuscript_selection","id":"man_01J...","locator":{"file":"main.tex","start":1840,"end":1912}},
  "expression":"f(x)=x^2-2x+1","format":"latex",
  "variables":[{"name":"x","domain":"real"}],
  "assumptions":["x >= 0"],"units":{},
  "capabilities":["numeric","symbolic","dimensions","inequality","counterexample"],
  "requested_mode":"auto"
}
```

返回 `verification.run`。若规范化表达或假设置信不足，run 进入 awaiting_confirm。

## 4.2 POST `/verifications/{verification_id}/confirm-normalization`

```json
{"normalized_expression":"Eq(f(x),(x-1)^2)","variables":[{"name":"x","domain":"real"}],"assumptions":["x >= 0"],"base_version":1}
```

## 4.3 GET `/verifications/{verification_id}`

顶层 verdict：`pass / unverifiable / counterexample / formal_pending`。能力卡：

```json
{
  "capability":"counterexample","status":"succeeded","verdict":"counterexample",
  "engine":{"name":"sympy","version":"locked"},"duration_ms":84,
  "evidence":{"assignment":{"x":-1},"constraints_satisfied":true,"left":"4","right":"0"},
  "resolved_mode":"local_engine","capabilities_used":["backend","sympy"],"missing_capabilities":[]
}
```

## 4.4 POST `/verifications/{verification_id}/promote-to-formal`

创建 FormalProject 草案并返回 `formal_pending` Evidence；携带规范表达、假设、来源和 return_context。

# 5. Lean4 形式化（后端正式能力）

## 5.1 POST `/formal/projects`

```json
{
  "project_id":"prj_01J...","title":"路径代价下界形式化",
  "template":"mathlib-basic","source_verification_id":"ver_01J...",
  "toolchain":{"lean":"locked","mathlib_commit":"locked-by-deployment"}
}
```

## 5.2 GET `/formal/projects/{formal_project_id}`

返回文件树、statement 状态、toolchain、Mathlib commit、最近 check/build 和缓存摘要。

## 5.3 PUT `/formal/projects/{id}/files/{path}`

路径必须在项目根内且扩展名白名单。Body：`{"content":"...","base_version":3}`。

## 5.4 POST `/formal/projects/{id}/statement-drafts`

自然语言→Lean statement 草案，可走星辰/本地模型。结果固定 `awaiting_confirm`，不得自动启动证明。

## 5.5 POST `/formal/projects/{id}/confirm-statement`

```json
{"file":"Main.lean","declaration_name":"cost_lower_bound","statement_hash":"sha256:...","confirmed":true}
```

## 5.6 POST `/formal/projects/{id}/check`

快速诊断，返回 `lean.check` run。可选 `files` 与 `target_declaration`。

## 5.7 POST `/formal/projects/{id}/build`

```json
{"target":"ResearchProject.Main","no_sorry":true,"requested_mode":"auto","return_context":{"type":"manuscript","id":"man_01J...","anchor":"eq:cost-bound"}}
```

返回 `lean.build` run。浏览器不得直接调用本端点后伪造本地成功。

## 5.8 POST `/formal/projects/{id}/tactics`

```json
{"file":"Main.lean","declaration":"cost_lower_bound","state_id":12,"tactic":"nlinarith","requested_mode":"auto"}
```

结果：`next_state / proof_finished / lean_error / proof_given_up / timed_out / out_of_memory / crashed`。

## 5.9 GET `/formal/runs/{run_id}/diagnostics`

```json
{
  "items":[{"uri":"project://Main.lean","range":{"start_line":14,"start_column":3,"end_line":14,"end_column":12},"severity":"error","code":"type_mismatch","message":"..."}],
  "proof":{"verdict":"not_verified","has_sorry":false,"open_goals":1,"kernel_accepted":false},
  "cache":{"hit":true,"key":"sha256:..."}
}
```

proof verdict：`verified / not_verified / formal_pending`。typed error code：`LEAN_SYNTAX_ERROR / LEAN_TYPE_ERROR / LEAN_OPEN_GOALS / LEAN_SORRY_FORBIDDEN / LEAN_TIMED_OUT / LEAN_OUT_OF_MEMORY / LEAN_DEPENDENCY_ERROR / LEAN_INFRA_ERROR`。

## 5.10 GET `/formal/projects/{id}/export`

导出 `.zip`：源码、lakefile、toolchain、manifest、README 和 hash；浏览器离线模式使用同一格式生成草案包。

# 6. LaTeX 写作

## 6.1 GET `/manuscript/templates`

过滤 `type=himcm|cumcm|journal|blank`、语言和领域。

## 6.2 POST `/manuscripts`、GET `/manuscripts/{id}`

创建空白/模板项目；详情含文件树、最近编译、citation key 冲突和 evidence 引用。

## 6.3 PUT `/manuscripts/{id}/files/{path}`

乐观锁保存；正文大于限制时返回 413。

## 6.4 POST `/manuscripts/{id}/imports`

Word/MD/Excel/图片公式导入，返回 `document.convert` run；完成 artifact 包含 AST/结构 diff，未确认不写入文件。

## 6.5 POST `/manuscripts/{id}/imports/{import_id}/confirm`

Body 含接受的 diff hunk 和目标路径。

## 6.6 POST `/manuscripts/{id}/compile`

```json
{"root_file":"main.tex","engine":"tectonic","synctex":true,"requested_mode":"auto"}
```

返回 `latex.compile` run；artifact：PDF、SyncTeX、结构化日志和输出清单。

## 6.7 GET `/manuscripts/{id}/compile/{run_id}/synctex`

参数支持 `source→pdf` 或 `pdf→source`。不可定位返回成功空结果与 `reason`，不返回 500。

## 6.8 POST `/manuscripts/{id}/suggestions`

类型：`polish / translate / structure / math_style`。建议绑定 source range 和 base_version；输出为待确认 diff。

## 6.9 POST `/manuscripts/{id}/suggestions/{suggestion_id}/decision`

`accept / reject / edit_and_accept`，乐观锁防止应用到已变化正文。

## 6.10 POST `/manuscripts/{id}/citations`

从项目文献库写入 CSL/Bib；检测 citation key 冲突后返回可选 key，不静默覆盖。

# 7. 论文初审

## 7.1 POST `/review-batches`

```json
{"project_id":"prj_01J...","title":"2026 校内建模初审","mode":"reviewer","rule_set":"himcm-2026","checks":["format","citations","symbols_dimensions","math_verification","language"]}
```

## 7.2 POST `/review-batches/{id}/papers`

multipart 最多 50 篇；每篇单独 document/review run。

## 7.3 GET `/review-batches/{id}`

返回分段计数：queued/running/succeeded/failed，以及 `attention_score`。响应固定：`ranking_disclaimer="人工关注优先级，不是论文排名"`。

## 7.4 GET `/review-papers/{paper_id}/report`

五层结果与问题项。reviewer 模式不下发 `suggested_fix`；作者模式可下发。每项含 page、quote、checker、confidence 和 evidence。

## 7.5 POST `/review-findings/{finding_id}/feedback`

Body：`{"decision":"useful|false_positive|needs_context","comment":"..."}`。

## 7.6 POST `/review-papers/{id}/reports/export`

返回 PDF 报告 run；首页必须带辅助性质与非排名声明。

# 8. 教育研究

## 8.1 GET `/education/data-products`

仅返回用户可申请的数据产品、字段、粒度、最小 k、保留期和用途限制。

## 8.2 POST `/education/datasets/preflight`

```json
{"product_id":"ldp_mastery_v2","scope":{"class_ids":["cls_01"],"date_from":"2026-03-01","date_to":"2026-07-01"},"dimensions":["week","knowledge_point"],"metrics":["mastery_mean","hint_dependency_rate"]}
```

返回预估行数、最小 cell_k、classification 和是否需审批；不返回数据。

## 8.3 POST `/education/datasets/query`

L1 且所有 cell k≥20 时创建不可变 DatasetSnapshot；否则 `422 PRIVACY_THRESHOLD_NOT_MET`。

## 8.4 POST `/education/datasets/exports`

L2 需要 `purpose / ethics_attestation / teacher_approval_id / admin_approval_id / expires_at`。导出文件写动态水印并进入审计。

## 8.5 POST `/education/analyses`

Body：snapshot、分析模板、参数、图表规范；返回统计 run。结果含 estimate、interval、assumptions、warnings、代码和环境版本。

## 8.6 POST `/education/charts`

导出 `png/svg/pdf/tikz/pgfplots`；artifact 绑定 dataset snapshot hash 和参数 hash。

# 9. 三端发布

## 9.1 POST `/publications`

```json
{
  "source":{"type":"evidence","id":"evd_01J...","version":2},
  "target":{"app":"teacher","container_type":"method_library","container_id":"mlib_01"},
  "policy":"copy_with_lineage","message":"已完成符号与 Lean 双验证"
}
```

返回 PublicationLink；需要审批时 status=`pending_approval`。

## 9.2 POST `/publications/{id}/approve`、`/reject`、`/retract`

撤回通知消费端并将链接设 retracted，不物理删除消费端已引用版本。

## 9.3 GET `/inbox`

科研端收件箱：学生推导、教师 ResearchBrief、审批请求、源资产变更和运行失败。

# 10. 星辰 WorkflowAdapter

## 10.1 注册表

后端维护：

```json
{
  "workflow_key":"wf_translate","provider":"xingchen","version":"2026-08",
  "input_schema_ref":"workflow://wf_translate/input/2026-08",
  "output_schema_ref":"workflow://wf_translate/output/2026-08",
  "timeout_seconds":600,"callback_signature":"hmac-sha256","fallback":"local_rules"
}
```

候选映射：`wf_translate`、`wf_paper_review`、`wf_formalize_draft`、`wf_research_assistant`。实际 key 由队友已有注册表提供；API 不依赖工作流内部节点。

## 10.2 回调 `POST /internal/workflows/callbacks/{run_id}`

校验签名、timestamp、nonce、run 状态和 schema version；重复回调幂等。工作流输出只生成 `ai_suggestion` 或 `awaiting_confirm` artifact。

## 10.3 熔断与本地降级

- 连续失败/超时达到部署阈值后 circuit open；新任务直接路由本地。
- 同一 run 不在未知状态下同时调用星辰和本地，避免重复输出。
- 本地无生成模型时返回规则结果或 evidence spans，`missing_capabilities` 写明。

# 11. 兼容性

- 旧 `POST /api/research/derivations/verify` 保留一个发布周期，内部映射 v2 Verification；响应增加 deprecation header。
- 旧 `/api/research/tasks/{id}` 映射 `/v2/runs/{id}`。
- M2 `/tools/verify/run` 可继续作为 worker 内部执行器，但 Web 不直接调用。
- v1 OpenAPI 只读归档；新开发必须导入 `m4_api_openapi_v2.0.json`。

# 12. 安全与审计

- Lean/TeX/Pandoc 无网络、非 root、只读依赖、临时写、路径白名单、产物白名单。
- 上传检查 MIME 魔数、大小、压缩炸弹、宏和路径穿越。
- 日志/事件不得包含完整论文、学生明细、JWT、API key 或工作流密钥。
- 审计事件：权限、statement 确认、证据采纳/撤回、L2 数据申请、导出、跨端发布和管理员操作。
- 对象存储下载使用短期签名 URL；敏感 artifact 绑定用户与用途。

# 13. 端点总表

| 域 | 端点数 | 核心端点 |
|---|---:|---|
| Capability/Run | 7 | capabilities、runs、events、cancel、retry、client sync |
| Project/Evidence | 8 | projects、activity、evidence、supersede、retract、repro package |
| Literature/KB | 9 | search、collections、imports、documents、blocks、citation verify/format、knowledge search |
| Verification | 4 | create、confirm、detail、promote formal |
| Formal/Lean | 10 | project、files、statement、check、build、tactic、diagnostics、export |
| Manuscript | 10 | templates、project、files、imports、compile、SyncTeX、suggestions、citations |
| Review | 6 | batches、papers、report、feedback、export |
| Education | 6 | products、preflight、query、export、analysis、charts |
| Publication | 5 | publish、approve、reject、retract、inbox |

