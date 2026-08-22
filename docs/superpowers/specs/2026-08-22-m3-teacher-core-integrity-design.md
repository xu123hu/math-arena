# M3 教师端可信核心批次设计

## 目标

让教师端的“选知识点出题—学生作答—教师确认评分”成为可验证、不可跨班越权、不会跨考点伪造内容的最小可信闭环。

## 边界

本批包含：带 `class_id` 列表的 scope 校验、题库测试隔离、知识点选择映射、题库不足策略、批改题目上下文、客观题标准答案比较。本批不修改现有脏文件 `ButlerPanel.vue`、`TeacherLayout.vue`、`TeacherNav.vue`、`router/index.js`、`teacher.css`；不引入新 agent 框架、队列或视觉重构。

## 设计

### 权限

所有可选 `class_id` 的查询遵循同一规则：传入时先调用 `assert_teacher_in_class`；未传时只从 `teacher_class_ids` 获取授权班级。越权返回稳定业务码 40302，不以空数组掩盖，也不返回资源存在性信息。

### 组卷

前端使用显式 `scope -> kp_code` 映射，不再硬编码。后端只从严格命中展开后知识点和题型的题库供题。题库不足时不再生成与知识点无关的方程/求导模板；返回已有严格命中题目并将 Artifact 标记 `degraded=true`、`content.insufficient=true`，警告中包含 requested/available，前端阻止直接发布并提示调整题量或范围。

难度配比在本批保持为 Artifact 审计字段，并按每个题型/难度槽位取题；没有足够题目时可以放宽难度，但不放宽知识点和题型。选择题必须有选项，所有题必须有答案；缺解析时明确标记“题库未提供解析，请教师补充”，不得虚构解析。

### 批改

`grading_detail` 通过 Submission 的 `quiz_id` 和 `item_no` 定位 QuizItem，返回 `assignment_title`、`question_text`、`question_type`、`options`、`standard_answer`、`answer_analysis`。默认学生标识保持匿名。

客观题建议仅在 QuizItem 和标准答案存在时做规范化比较（去除首尾空白、英文字母大小写不敏感）；正确返回满分参考 1.0 和高置信度，错误返回 0 和高置信度。无法定位题目或标准答案时建议分为空/0、低置信并明确 `needs_review=true`，文案不得声称已按标准答案判定。

## 错误与降级

- 跨班：40302。
- 题库不足：成功返回可编辑 Artifact，但 `insufficient=true` 且前端禁止发布。
- 标准答案缺失：不自动判分，转人工复核。
- 旧数据没有 QuizItem：批改详情仍显示原答与人工复核提示，不发生 500。

## 测试

- 后端 API 集成测试覆盖跨班列表、题库测试隔离、严格 KP 不跨考点、题库不足标记、正确/错误客观答案、无标准答案与详情上下文。
- 前端组件/纯函数测试覆盖 scope 映射和不足时发布门；批改详情类型和页面以 E2E 重建任务覆盖。
- 全量运行教师专项、前端 Vitest、前端构建；科研端既有 typecheck 债务单独报告。
