# M3 教师端后端执行日志

> 依据：`D:\M2开发\M3教师端\_M3教师端后端全自动开发主提示词_v1.0.md`
> 目标：在 `D:\math-arena` 连续开发 M3 教师端后端，不中断到最终验收或真实停止条件。

## 基线
- 阶段 6 / 6A 绿色独立提交：`5054325`（feat: prewire butler web_search_opt_in transport chain）
- M3 基线 HEAD：`5054325`
- 工作区遗留修改（与本任务无关，绝不触碰/暂存/提交）：apps/web 删除项、.env.example、.gitignore、CI、多份未跟踪 `_diag_*`/scripts/eval 等

## 追踪矩阵（需求 → API → Service/Tool → 数据表 → 测试）
| 需求 | API | Service/Tool | 表 | 测试 |
|---|---|---|---|---|
| F0 Today | GET /api/teacher/today | today.py | 聚合 | test_m3_teacher_today_insights.py |
| F6 洞察 | GET /api/teacher/classes/{id}/insights | insights.py | actionable_insights | 同上 |
| F1 备课 | POST /api/teacher/lessons/adapt | lessons.py, capability_gateway | teaching_artifacts | test_m3_teacher_lessons.py |
| F3 作业/出题 | POST /api/teacher/quizzes/generate | assessment.py | teaching_artifacts+assignments | test_m3_teacher_assessment.py |
| F4 批改 | grading/suggest/confirm | grading.py | submission_items+teaching_artifacts | test_m3_teacher_grading.py |
| F7 课堂 | POST classroom-mode / video-insights | classroom.py | — | test_m3_teacher_classroom.py |
| F2/F11 课件/讲解 | lessons/slides, lessons/explainer | lessons.py | teaching_artifacts | test_m3_teacher_lessons.py |
| 资源 | resources/upload/preprocess/understand | resources.py | teacher_tasks | test_m3_teacher_resources.py |
| Capability | POST /api/ai/capabilities/{cap} | capability_gateway.py, registry.py | teaching_artifacts | test_m3_teacher_capabilities.py |
| Artifact | artifacts/* | artifacts.py | teaching_artifacts+teacher_actions | test_m3_teacher_artifacts.py |
| 范围 | — | scope.py | class_members | test_m3_teacher_scope.py |
| 任务 | tasks/* | — | teacher_tasks | test_m3_teacher_resources.py |
| channel | 全部 | registry_policy.py | — | test_m3_teacher_registry_policy.py |
| E2E | 全部 | — | — | test_m3_teacher_e2e.py |

## 提交链
- 待定（每完成一个逻辑块独立提交）