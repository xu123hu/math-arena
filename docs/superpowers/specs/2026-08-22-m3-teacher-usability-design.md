# M3 教师端可用性与准入批次设计

## 目标

在不覆盖用户现有 Butler、布局、路由聚合和全局样式未提交改动的前提下，把教师端从“可信核心可用”推进到“教师能输入真实课题、审阅真实内容、看到可信身份与数据、拒绝无效材料”的可工作状态。

## 边界

本批包含：数据库实时教师准入、备课课题与教案 Artifact 回填、组卷内容完整性与教师预览、Today/班级自然语言和成员/邀请码、0B 资源门禁与摘要回归。

本批不修改原始 dirty 文件：`ButlerPanel.vue`、`TeacherLayout.vue`、`TeacherNav.vue`、`router/index.js`、`src/api/index.js`、`teacher.css`、后端 Butler workflow 文件。教学助手的“上下文→工具→Artifact→确认”单独排期；真正异步 worker、课堂新工具、全局视觉重构不在本批。

## 教师准入

JWT 的 `active_role=teacher` 只表达当前会话意图，不是持续授权事实。每个 `/api/teacher/*` 请求必须在数据库存在 `RoleBinding(role='teacher', verified=true, deleted_at is null)`。缺失、待审核、撤销统一返回 403 / 40301，且在进入任何业务查询前完成。

测试 helper 默认创建已审核绑定，避免把“伪造 teacher token”误当成正常教师；专项测试覆盖未绑定、未审核、软删/撤销和 token 签发后撤销。

## 备课 Artifact

教师显式输入课题、课时和班情要求；空课题不发请求。`adapt_lesson` 无论外部模型是否可用，都返回可审阅的 draft：课题、目标、重难点和逐环节 `activities`。本地降级内容按真实课题生成，明确是可编辑草稿，不出现“不知道”、空壳或 `Exit Ticket`。

前端必须原样回填 Artifact 的 topic/objectives/timeline activities；重新打开已有 Artifact 不丢字段。生成 PPT 不得隐式确认 draft：教师先独立确认教案，再显式生成并下载非空 PPTX。

## 组卷完整性

严格知识点命中只是底线。可发布的 choice 还必须具备可枚举选项、非空标准答案；解析缺失时保留题目但明确标记“题库未提供解析，请教师补充”，并在预览中可见。缺选项或答案的 choice 不进入可用题数，从而触发现有 `insufficient` 发布门禁。

前端 `QuizQuestion` 兼容对象或数组选项，统一消费后端 `analysis` 字段；每题预览显示选项、标准答案和解析/缺失提示。blank/text 不展示伪选项。

## Today 与班级可信呈现

称呼规则：昵称已以“老师”结尾时不重复；普通昵称追加“老师”；无昵称显示“老师”。洞察 evidence 按 kind 转成教师自然语言，保留样本量/比较窗口，但不得暴露 `count=`、`recent_count=` 等内部键值串。

班级成员接口同时返回用户昵称和班内昵称，展示时优先班内昵称；班级统计区分学生与教师。教师自己的班级列表可返回并展示邀请码，学生路径不得得到邀请码。

## 资源门禁

后端读取上传内容后、创建目录/数据库记录/任务前拒绝 0B 文件，返回稳定 `40001/resource_empty`。前端在选择文件时同步预检并给教师自然语言提示。非空资源的解析/摘要链路保持不变，摘要完成后同一卡片立即可见。

## 验证

- 所有行为先 RED 后 GREEN，并按两个仓库分别提交。
- 后端运行全部 `test_m3_teacher*.py`、相关 classroom 测试、Ruff 和 diff-check。
- 前端运行聚焦组件测试、全量 Vitest、typecheck、build、隔离端口 teacher E2E。
- 每个任务独立实现审查；批次结束进行跨仓总审与 dirty-path 冲突检查。

