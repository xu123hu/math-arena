# M3 教师端—学生端联动设计

## 1. 作业布置

教师确认 quiz Artifact → 创建 M2 Assignment draft → 幂等 publish 改为 published → 学生 `/api/assignments` 只读已发布任务。未发布不可见；不建第二套作业表。

## 2. 学情聚合

学生 Submission/SubmissionItem/Mastery/视频事件 → 本地 SQL 按 class scope 聚合 → Today/Classes ActionableInsight。默认只返回统计依据、时间窗和动作，不返回逐人敏感画像。

## 3. 批改确认

学生 SubmissionItem → AI suggestion draft → 教师 accept/override → 同一事务写 teacher_final_score、兼容 score、Submission 汇总与审计 → 后续 mastery 更新幂等执行。确认前正式分不变。

## 4. 课堂模式

教师确认启停 → ClassroomMode 写入 settings/started_by/expires_at → 学生端按班级成员 scope 读取有效状态 → TTL 过期视为关闭。无事件源时参与度为空且 degraded，不伪造在线人数。

## 5. 资源

教师 multipart 上传 → 复用 File/对象存储 → TeacherTask 预处理 → KB 索引/来源定位 → 教案引用；只有显式发布/授权资源对学生可见。失败保留可恢复任务状态。

## 6. 双师课堂

Class owner 或 `class_members(member_role=teacher, confirmed=true)` 共享同一 class scope；操作使用实际 teacher_id 写审计，课堂模式以 class_id 为共享真相。未确认成员、学生或其他班教师按 404/403 稳定拒绝。

## 接口与兼容表

| 场景 | 教师接口 | 学生/共享接口 | M2 复用 |
|---|---|---|---|
| 作业 | `/api/teacher/assignments*` | `/api/assignments` | assignments、assignment_targets、quizzes |
| 学情 | `/api/teacher/today`、`classes/{id}/insights` | 学生提交/掌握度写路 | submissions、submission_items、mastery_records |
| 批改 | `/api/teacher/grading*` | 学生成绩读取 | submission_items、submissions |
| 课堂 | `/api/teacher/classes/{id}/classroom-mode` | `/api/classes/{id}/classroom-mode` | classes、class_members；新增 classroom_modes |
| 资源 | `/api/teacher/resources*` | 已发布资源/KB 读取 | files、courses、kb |
| 双师 | 全部 class-scoped 接口 | 无额外端点 | classes、class_members |
