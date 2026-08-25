# 迁移合链方案：worktree（m2_*/m3_* 扩展）并入开发库（D:\math-arena）

> 2026-08-25 · 结论基于双侧 alembic heads 实测定案

## 一、现状（实测）
| 项 | worktree（本次改动） | 开发库 D:\math-arena |
|---|---|---|
| 基线 | e544 初始15表 → 1d710 pgvector → a3f2 user_configs → auth_001（与 dev 同源） | 同左 |
| 主干扩展链 | auth_001 → m2_001…m2_018 → m3_001 → m3_002 | 同左（另含 m3_003_grading_v2_workspace） |
| 本次新增 | m2_019_submission_attachments、m2_020_classroom_sessions | auth_002_role_selective_sms → om1 → om2_openmaic_document（OpenMAIC 接入链） |
| alembic head | m2_020_classroom_sessions（单头 ✓） | m3_003_grading_v2_workspace（单头 ✓） |

两链共享同一 auth_001 与 m2/m3 主干，并非两条独立遗传树，合链复杂度低。

## 二、目标与原则
- 目标：开发库升级后新增两张表：submission_items.attachments（多图附件）、classroom_sessions（AI 课堂会话，course_id 可空，含 updated_at）。
- 原则：不改动任何已应用迁移；在 dev 当前 head 之后追加新迁移（保持单头）；与 dev 正在跑的 om2_openmaic_*（OpenMAIC 文档接入）互不冲突（独立命名）。

## 三、推荐合链步骤（需你在开发库环境执行）
1. 复制 worktree 两个迁移到 dev 仓库，并改 down_revision：
   - services/api/alembic/versions/om3_001_submission_attachments.py：down_revision = "m3_003_grading_v2_workspace"，revision = "om3_001_submission_attachments"（内容 = 现 m2_019）
   - services/api/alembic/versions/om3_002_classroom_sessions.py：down_revision = "om3_001_submission_attachments"，revision = "om3_002_classroom_sessions"（内容 = 现 m2_020，含 course_id nullable + updated_at）
2. 校验单头：alembic heads 应只有 om3_002_classroom_sessions
3. 测试库演练：先在 math_arena_wt 上 alembic upgrade head 验证可运行
4. 开发库执行：alembic upgrade head（补跑 m3_003 → om3_001 → om3_002）
5. 冒烟：classroom_sessions / submission_items.attachments 可用；om2_openmaic_* 表不受影响

## 四、替代方案
- 维持两套库：dev 库跑 om 链；本特性随下次合入分支时自然携带（本地联调仍需独立测试库）。

## 五、风险与回滚
- 低风险：两张新表/一列，无改造既有表结构。
- 回滚：alembic downgrade om3_001（drop classroom_sessions / 回滚列），不触碰 om2 链。
- 注意：m2_019 revision id 已改名（m2_019_submission_item_attachments → m2_019_submission_attachments，规避 varchar(32) 超长）——合链用短版 id。