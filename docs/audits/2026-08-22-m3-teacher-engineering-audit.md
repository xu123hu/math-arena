# M3 教师端工程收尾审计（2026-08-22）

## 审计范围

本文档闭环 `docs/superpowers/plans/2026-08-22-m3-teacher-core-integrity.md` 与
`docs/superpowers/plans/2026-08-22-m3-fullstack-closure.md` 的最终集成与验证步骤，
并记录教师端工作流（codex/teacher-core-backend，19 个提交）并入 feat/backend-m1 的
冲突解决方案与证据。前序诊断见
`docs/superpowers/audits/2026-08-22-m3-teacher-deep-optimization-audit.md`。

## 集成内容

- 合并提交：`83f5a4f`（Merge branch 'codex/teacher-core-backend' into feat/backend-m1）
- 适配提交：`c6701f4`（test(m3): align teacher scope and profile gates with unified auth）
- 分支内容：教师准入绑定核验、跨班隔离、知识点忠实组卷、题库不足门禁、客观题判分、
  批改上下文与证据不可变、评分确认生命周期、确定性备课草稿与生命周期校验、
  资源/课堂/Today/洞察修复（提交 d0f6353..e67b79d）。

## 冲突解决记录

两侧（统一认证 vs 教师核心）仅两个测试基础设施文件冲突，无业务代码冲突：

| 文件 | 解决方案 |
| --- | --- |
| `tests/conftest.py` | 融合双方：保留认证侧"重试一次 + drop/create + public 表数量核对（63/63）+ 失败不静默"，叠加教师侧"DROP SCHEMA 级重建 + current_database() 守卫"，守卫置于 `_init` 事务内 |
| `tests/_m3_helpers.py` | `make_user` 融合双语义：student/researcher/admin 恒为 approved 绑定（认证侧角色切换契约），teacher 绑定由 `teacher_verified` 参数控制（True=approved / False=pending / None=无绑定） |

合并后模型适配（非冲突、语义修复）：

| 文件 | 问题 | 修复 |
| --- | --- | --- |
| `app/domains/teacher/scope.py` | 基线 `verified` 为真实列；统一认证后为派生 property（SSOT=status），`RoleBinding.verified.is_(True)` 在运行时会崩溃 | 改为 `RoleBinding.status == "approved"` 查询过滤 |
| `tests/test_m3_teacher_scope.py` | 4 个用例期望教师 scope 层 40301；统一认证网关 `get_current_user` 已在请求时实时校验 approved 绑定并先返回 40300 | 断言更新为 40300，并在用例文档注明双层失败关闭语义（网关 40300 → scope 40301 二次防线） |
| `tests/test_m3_teacher_profile.py` | 子进程 pop `M3_ENABLE_TEACHER` 后回退读取本地 `.env`（内含 true）导致门控测试假失败 | 子进程环境显式 `M3_ENABLE_TEACHER=false` 覆盖；默认 false 契约由 `app/config.py` 定义保证 |

## 需求到测试证据

| 需求 | 证据（测试文件，合并后全绿） |
| --- | --- |
| 教师准入（数据库绑定核验、撤销即拒绝） | `test_m3_teacher_scope.py`（22 项，含网关 40300 与 scope 40301 双层） |
| 跨班隔离（assignments/queue 显式 class_id 40302） | `test_m3_teacher_scope.py` |
| 知识点忠实组卷 / 题库不足门禁 | `test_m3_teacher_assessment.py` |
| 客观题判分 / 批改上下文 / 证据不可变 / 确认幂等 | `test_m3_teacher_grading.py` |
| 确定性备课草稿 / 生命周期校验 / PPTX 与 DOCX 真实下载 | `test_m3_teacher_lessons.py` |
| 课堂模式 DB 持久化 / 教学闭环（发布→提交→批改→反馈） | `test_m3_fullstack_closure.py`（schema、classroom、全链路） |
| 资源真实工作流（上传/抽取/理解/发布/下载） | `test_m3_teacher_resources.py` |
| Today / 洞察 / Artifact / Butler / 能力降级 / 注册策略 | `test_m3_teacher_today_insights.py`、`test_m3_teacher_artifacts.py`、`test_m3_teacher_butler_chat.py`、`test_m3_teacher_capabilities.py`、`test_m3_teacher_registry_policy.py` |
| M3 门控默认关闭 / Alembic 单头 | `test_m3_teacher_profile.py` |
| 统一认证回归（合并线共存） | `tests/identity/`（16 文件） |

## 验证运行（2026-08-23 实测）

| 项 | 命令/方式 | 结果 |
| --- | --- | --- |
| 工作树基线（集成前） | pytest 15 个 test_m3_* 文件 | 127 passed |
| 合并后教师端+身份 | 同上 + `tests/identity` | **199 passed**（conftest 表数量核对 63/63） |
| 聚焦回归 | `test_m3_teacher_scope.py` + `test_m3_teacher_profile.py` | 22 passed |
| Ruff | `ruff check`（5 个涉改文件） | All checks passed |
| 前端单测 | `npm test`（D:\frontend） | 71/73 passed（2 失败为预存，见残留限制） |
| 前端构建 | `npm run build` | 通过（5.95s） |
| Alembic | `alembic upgrade head`（开发库 math_arena） | m3_002 → auth_001 成功；旧角色绑定迁移：student 3、teacher 2 条 approved |

## 残留限制（不含未支撑的完成声明）

1. **真实浏览器 E2E 未在本会话重跑**：fullstack-closure 计划 Task 6 的浏览器逐菜单
   验证（登录→备课→发布→提交→批改→下载）由 API 级闭环测试代证
   （`test_m3_fullstack_closure.py::test_published_assignment_student_submit_teacher_grade_student_result`）。
   Docker 全栈起停 + 浏览器走查仍待人工或后续会话执行。
2. **前端 2 个预存失败**：`test/auth/securityPages.test.ts` 两项，根因是工作区未提交的
   M2 科研/管理端改动（`AdminNav.vue` 等），与教师端无关，本批未触碰（保留用户脏区约束）。
3. **后端全仓套件未整体重跑**：主工作区存在大量用户未提交 M2 改动（butler/gateway/测试），
   全仓结果会混入用户在制工作；本批以两条合并线（M3 教师 + identity）的 199 项聚焦绿为准。
4. **教师 scope 40301 二次防线在网关生效时不可直达**：`require_verified_teacher` 保留为
   纵深防御（网关配置变化或其他入口路径下仍生效），当前主路径由网关 40300 拦截。
5. **Docker 镜像与部署链**（`42dc582c5561_math-arena-api` 退出码 1 的旧容器）未重建验证，
   生产 compose 起停属部署阶段工作。

## 结论

教师核心完整性批次与全栈闭环批次的后端工作已全部并入 `feat/backend-m1` 并与统一认证
线共存：合并适配后 199/199 聚焦测试绿、前端教师端零回归、开发库迁移升至唯一 head
（auth_001_unified_identity）。剩余事项仅为上节 1–5 所列的非代码验证与用户在制 M2
工作的独立收敛。
