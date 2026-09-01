# 双师课堂教材 RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将五册人教 A 版学生教材真实入库，并让双师课堂以有证据的题目 Agentic RAG、受控图形或教材关联完成可验证讲解。

**Architecture:** 继续使用既有 `EmbeddingProvider`、`RAGPipeline`、MiMo V2.5、课堂 `stage_router` 与 GeoGebra 服务。教材导入扩展为“教材章节→知识点”映射；课堂层在已有检索前增加输入分析和检索计划，并将结构化教材关联作为无图时的安全替代。

**Tech Stack:** FastAPI、SQLAlchemy/PostgreSQL pgvector、SentenceTransformers BGE-M3、Vue 3、Vitest、pytest、Playwright。

**Spec:** `docs/superpowers/specs/2026-08-29-dual-teacher-grounded-rag-design.md`

## Global Constraints

- 仅导入白名单五册人教 A 版 2019 学生教材；教师用书、题库和研究资料不得进入 `scope=student` 教材证据域。
- 复用现有向量、RAG、MiMo、数学验证与 GeoGebra；不增加新向量库、图形 DSL 或 OCR 管线。
- 生产代码不得读取金标准答案或按题干关键词特判。
- 任何题图不确定项、无教材证据、数学验证失败或图形契约不完整时都不得伪造 ready、图形或引用。

---

### Task 1: 恢复 BGE-M3 本地嵌入服务

**Files:**
- Modify: `services/api/scripts/local_embedding_server.py`
- Modify: `services/api/tests/test_local_embedding_server.py`

**Interfaces:**
- Produces: `/health` 返回已加载模型和 1024 维；`POST /v1/embeddings` 返回与输入等长的归一化向量。

- [ ] 写一个失败测试：模型文件不完整时健康检查必须为失败，禁止加载或返回随机向量。
- [ ] 运行该测试，确认失败原因是现有服务没有完整性检查。
- [ ] 为模型权重完整性、模型加载和启动失败提供明确错误；下载/恢复真实模型后以真实文本调用接口。
- [ ] 运行 `pytest tests/test_local_embedding_server.py -q` 与实际 HTTP 健康检查。

### Task 2: 教材知识点树与原子导入

**Files:**
- Modify: `services/api/scripts/import_pep_textbooks.py`
- Create: `services/api/scripts/seed_pep_textbook_kps.py`
- Modify: `services/api/tests/test_import_pep_textbooks.py`

**Interfaces:**
- Produces: `ensure_pep_textbook_knowledge_points(db, batches) -> dict[str, uuid.UUID]`。
- Produces: 导入切片的 `kp_ids` 非空，且 `meta` 保留册、节、小节与源 chunk。

- [ ] 写失败测试：教材章节生成稳定的高中数学知识点 code；切片写入匹配的 `kp_ids`。
- [ ] 运行测试，确认现有导入将 `kp_ids=[]`。
- [ ] 只从白名单教材目录和章节标题建立树，事务性写入五册与 792 切片。
- [ ] 运行导入 dry-run、真实导入、数据库计数和按知识点检索测试。

### Task 3: 题目 Agentic RAG 编排与教材引用

**Files:**
- Create: `services/api/app/domains/classroom/rag_orchestrator.py`
- Modify: `services/api/app/domains/classroom/openmaic_adapter.py`
- Modify: `services/api/app/domains/classroom/stage_router.py`
- Create: `services/api/tests/test_classroom_rag_orchestrator.py`

**Interfaces:**
- Produces: `build_classroom_retrieval_plan(source, parse_quality) -> ClassroomRetrievalPlan`。
- Produces: `retrieve_classroom_evidence(plan, db, rag) -> ClassroomEvidence`，带书、节、chunk、检索理由。

- [ ] 写失败测试：手输知识点产生学生教材检索计划；含不确定题图被阻断；图形实体进入检索查询。
- [ ] 运行测试，确认接口不存在。
- [ ] 复用 `RAGPipeline.retrieve` 及它的重排，不建立平行检索；将引用和计划持久化到课堂 `source_ref/verification`。
- [ ] 运行单元和数据库集成测试，确认无命中显式返回 unavailable。

### Task 4: 图形空位的教材关联与前端渲染

**Files:**
- Modify: `services/api/app/domains/classroom/stage_router.py`
- Modify: `services/api/app/domains/classroom/openmaic_adapter.py`
- Modify: `D:\frontend\src\utils\dualClassroom.js`
- Modify: `D:\frontend\src\pages\student\DualView.vue`
- Create/Modify: `D:\frontend\test\student\dualClassroom.test.ts`

**Interfaces:**
- Produces: `{kind: 'textbook_association', citations, relation_reason}` block when visual is unsafe or absent but evidence exists.
- Consumes: verified GeoGebra blocks unchanged when all visual gates pass.

- [ ] 写失败测试：没有图形但有证据时课堂块包含教材关联；无证据不伪造关联；前端将其归入图形示意区。
- [ ] 运行测试，确认现有代码没有该 block。
- [ ] 追加安全回退和教材关联卡片，避免默认 3D 图补位。
- [ ] 运行 pytest、Vitest 和前端构建。

### Task 5: 两道真实题的端到端验收

**Files:**
- Create: `services/api/tests/fixtures/dual_teacher_goldens.json`
- Create: `services/api/tests/test_dual_teacher_e2e_goldens.py`
- Create: `deliverables/dual-teacher-grounded-rag/README.md`

**Interfaces:**
- Produces: 函数和空间几何各一条非生产夹具，记录预期结论而非生产答案。
- Produces: 验收报告、检索证据、验证结果及 5176 页面截图。

- [ ] 写失败测试：通用验收夹具须检查证据、推导/答案及图形或教材关联；金标准数据不得从 production 模块导入。
- [ ] 运行测试，确认夹具不存在。
- [ ] 用真实后端生成两题课堂；对每页验证、答案与视觉决策进行断言。
- [ ] 用 Playwright 截图 5176 的两条运行结果；运行全量目标测试和前端构建。
