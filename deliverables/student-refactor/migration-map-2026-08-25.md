# 学生端改造 · 参考项目迁移映射（2026-08-25）

> 背景：学生端错题本、知识图谱、学情总览"脱离学生"，课堂任务不支持图片作业上传；
> 双师课堂（OpenMAIC）只是死壳。本次按"参照 GitHub 优秀项目，严格个性化模仿，非必要不原创"原则迁移。
> 参考仓库已 clone 到 D 盘根目录：`D:\OpenTutor`、`D:\open-mastery`、`D:\Plot-Ark`、`D:\Math-OCR-System`
>（另保留调研目录 `D:\双师课堂调研\OpenMAIC`、`D:\双师课堂调研\OpenTutor`）。

## 1. 现状诊断（有代码证据）

| 功能 | 现状 | 症结 |
|---|---|---|
| 双师课堂 DualView | `D:\frontend\src\pages\student\DualView.vue`：读 `current.openmaic.classroom_url` 的 iframe 为**死代码**（后端 course_router 从不返回该字段），实际展示全模拟面板（假播放/假问答/假笔记） | 无真实课堂生成与数据流 |
| 课堂任务图片上传 | `SubmissionItem.file_id` 单文件字段；前端仅解答题可拍 1 张（useSolutionPhoto） | 无多图附件、非解答题不能附图 |
| 错题本 | ErrorsView 有 FSRS 热力图/到期队列/苏格拉底答疑（接口由 growth_router 提供，真实存在） | 缺"主动拍照入本"闭环；星系/部分交互是占位 |
| 知识图谱 | GraphView 树形+ALEKS 饼图真实数据；"星系"按钮只弹 toast"演示版" | 星系视图是假的 |
| 学情总览 | OverviewView 学习闭环/综合分/今日3件事/功能入口均真实 API | 缺课堂任务联动卡 |

## 2. 参考项目剖析要点（迁移参照）

### 2.1 OpenTutor（Next.js web + FastAPI apps/api）— 错题/复习/进度
- **FSRS-5/6 21 参数**：`D:\OpenTutor\apps\api\services\spaced_repetition\fsrs.py`（L35-44 参数、L72-157 状态机）
  我们后端已有 FSRS 缓存列（error_records.fsrs_*）与复习接口，无需重搬算法，沿用现有实现。
- **错题复习工作流**：`routers/wrong_answers.py`（L37-123 list/filter/retry/mark-mastered）
  → 我们的 ErrorsView 到期队列/复习流与其同构，已存在，无需迁移。
- **进度/掌握度**：`services/progress/tracker.py`（weighted/BKT mastery + gap type）、`routers/progress.py`
  → 我们已有 MasteryRecord(BKT) + growth 聚合，同构。
- **知识图谱构建**：`services/knowledge/graph.py`（D3 节点/边 + 掌握度上色）
  → GraphView 的 tree/pie/deps 已同构。
- **结论**：OpenTutor 的核心价值已在我们后端沉淀；前端交互（flashcard-panel 评分 UI、progress-panel 分段条）可作为后续打磨参照。

### 2.2 open-mastery — 高中数学知识图谱 DAG（任务二C 参照）
- `D:\open-mastery\graph`：**131 节点高中数学知识图谱**数据文件（节点/边/前置关系 YAML）
- `engine/`：**"下一步学什么"** 查询引擎（后继推荐 = 满足前置且未掌握）
- `web/skilltree`：技能树视图（层级 + 掌握状态）
- **落地**：我们知识图谱后端已含 `KpPrerequisite`（前置关系）与掌握度；星系视图（本周已实现）即"技能树"的力导向变体；下一步可将前置链（deps.chain）与推荐理由（recommend.reason）强化为"下一步学什么"口径。

### 2.3 Plot-Ark — 学情面板 + 图谱可视化（任务二D 参照）
- `D:\Plot-Ark\backend\routes\selfview.py`：学生自视聚合（模块级 visits/revisits、verb 分布、**7×24 学习节律矩阵** L80-111）
- `backend\routes\graph.py`：LightRAG → networkx → nodes/edges JSON（react-force-graph-2d 数据源）
- **落地**：OverviewView 已真实化（综合分/闭环/今日3件事）；本周新增"课堂任务速览卡"（`/student/assignments` 真实数据）。7×24 节律矩阵可作为后续"学习日历/专注度"卡片参照。

### 2.4 Math-OCR-System — 数学公式照片识别（任务二 图片上传参照）
- `D:\Math-OCR-System\src\app\main.py`（L43-83）：上传→图像预处理→Texify→dual-LaTeX
- `src\ocr\hybrid_ocr.py`（L37-62）：Texify 主 + Pix2Tex 兜底双引擎
- **依赖代价**：Texify 模型体积大、需 GPU/大内存，不适合直接搬入。
- **我们的等效能力（已存在）**：`services/api/app/domains/files/router.py` RapidOCR 本地轨 +
  星辰 `wf_doc_understand` 云轨（输出 LaTeX + confidence + 低置信闸门 + 人工复核降级），
  与 Math-OCR 的"拍照→LaTeX"目标等价且已生产化。
- **本周落地**：`SubmissionItem.attachments` 多图附件（迁移 m2_019）+ OCR 回填 + 纯照片不判 0 分（走教师复核）+ 教师端批改序列化透传附件；前端新增 `HomeworkPhotos.vue` 多图上传组件（压缩/预签名/解析轮询/回填）。

## 3. 迁移落地清单（已完成 · 本次）

### 后端（services/api，worktree）
1. `app/models/coursework.py` + `alembic/versions/m2_019_submission_item_attachments.py`
   - `submission_items.attachments` JSONB（多图附件）
2. `app/gateway/student_router.py`（practice/submit）
   - 附件归属校验、逐附件 OCR 回填、纯图片作答 pending_review（不判 0 分）、结果展示 attachments
3. `app/domains/teacher/grading.py`（两处序列化）→ 附件透传给教师批改端
4. `app/models/classroom.py` + `alembic/versions/m2_020_classroom_sessions.py`
   - AI 数学课堂会话（outlines + slides + 状态）
5. `app/domains/classroom/stage_router.py`（/api/classroom/*）
   - 两段式生成：高中数学专属大纲（8~15 页，导入/概念/公式/例题/小结，kp 白名单，LaTeX）+ 逐页内容（text/latex/example/note + 旁白），LLM 失败确定性兜底
6. `app/domains/classroom/course_router.py`（GET /courses）
   - 学生可见"已确认班级"内教师登记的课程（与教师端数据打通）
7. `app/main.py` 挂载 `classroom_stage_router`

### 前端（D:\frontend）
1. `src/components/student/HomeworkPhotos.vue`（新）—— 多图上传/OCR/预览/移除/回填
2. `src/pages/student/AssignmentView.vue` —— 各题型均支持多图附件、结果缩略图
3. `src/pages/student/ErrorsView.vue` —— 「拍错题入本」主动收录闭环（OCR 题干 + 错因/知识点 + 备注）
4. `src/pages/student/GraphView.vue` —— 星系视图真实化（章节分层环 + 掌握度上色 + 节点联动）
5. `src/pages/student/OverviewView.vue` —— 课堂任务速览卡（真实 /student/assignments 数据）
6. `src/api/index.js` —— 新增 `classroomApi`
7. `src/pages/student/DualView.vue` —— 重写为真实课堂播放器（生成配置/进度轮询/幻灯片渲染/大纲栏/朗读/笔记/看课检测）

## 4. 对标"真实备课场景"的闭环（本次打通）

教师登记课程（ASR 字幕）→ 预处理（章节/知识点/知识卡）→ 学生端 /courses 可见班级课程 →
生成多页 AI 数学课堂（大纲→内容两段式）→ 学生播放 + 随讲随问 + 课堂检测（复用 F2 出题）→
错题自动收录 + FSRS 排期复习 → 知识图谱/学情更新 → 作业（含图片附件）提交 → 教师批改端复核 → 结果回流。

## 6. 本地公式识别 · mimo（小米模型）依赖/模型评估（2026-08-25）

### 6.1 现状识别链路（已生产）
- `services/api/app/domains/files/router.py`：
  - 本地轨 `_parse_image_rapidocr`（RapidOCR ONNX）：纯文字可读，公式结构失真（f'(1)→f(1、x²→x~2）
  - 云轨 `_parse_image_vision`（星辰 `wf_doc_understand`）：输出 LaTeX + confidence + 低置信闸门 + 人工复核降级，**当前拍照识别主力**
  - 双轨策略：question_photo 优先云轨，失败降级本地 OCR / manual_photo_review

### 6.2 mimo 接入现状（有代码证据）
- `app/config.py:33` `deepseek_base_url = "https://api.xiaomimimo.com/v1/chat/completions"` —— **DeepSeek provider 直连小米官方 API**
- `app/providers/deepseek.py:67-85` `_build_payload`：`messages` 原样写入 OpenAI 兼容 body（无障碍传递多模态消息的通道能力成立）
- `app/gateway/agent_router.py:1006` 注释：**MiMo 已是 chat 主力**；socratic/chat 场景对 infinite_thinking 有过适配（mimo 思考产语速实测约 7-8s）

### 6.3 候选方案评估矩阵（已实机探测核实）

| 方案 | 能力(图片→LaTeX) | 实测结果 | 结论 |
|---|---|---|---|
| A. mimo 直调视觉（image_url 透传） | ❌ **不支持** | 2026-08-25 实机探测：POST 手写公式图到 `api.xiaomimimo.com/v1/chat/completions` 返回 **HTTP 404** `"No endpoints found that support image input"` | **已否决** |
| B. 二段式：RapidOCR 文本 → mimo 规整 LaTeX | ✅（无视觉依赖） | 已接线（`files/router.py` `_rewrite_ocr_to_latex_with_mimo` + question_photo 主链路），生产降级链：mimo_rewrite → wf_doc_understand → rapidocr → 人工复核 | **已实施** |
| C. 本地 ONNX 小模型（qrt-latex-lite / Texify 蒸馏） | 是（专用模型） | 模型 ~100-300MB、集成/维护成本高 | 中后期规模化备选 |

### 6.4 接入点（B 已实现）
- `files/router.py`：新增 `_rewrite_ocr_to_latex_with_mimo`（rapidocr 本地文本 → mimo 规整 LaTeX，prompt 保留题意/数值、公式 $...$ 包裹、输出含数字才采纳），在 question_photo 主链路优先于云轨执行；云轨分支以 `parse_engine != "mimo_rewrite"` 守卫避免覆盖
- 降级链实测保持：`mimo_rewrite → wf_doc_understand → rapidocr → manual_photo_review`（铁律：低置信不静默使用，confidence=0.0 走人工复核）

### 6.5 待办（需真实环境的动作）
1. ✅ 方案 A 探测已执行并否决（mimo 不支持 image_url）；✅ 方案 B 已接线（mimo_rewrite）
2. 用 3-5 张真实手写作业图走一遍完整链路，核对 `mimo_rewrite` 的 LaTeX 质量与"数值保留/不改题"纪律，必要时调 prompt 温度与 `_RAPIDOCR_MIN_TEXT_LEN` 阈值
3. 本地 ONNX 方案（C）作为独立任务立项，评估 qrt-latex-lite 精度与量化体积

## 7. 后续建议（不在本次范围）

- OpenMAIC 白板/交互组件、OpenTutor 闪卡评分 UI、Plot-Ark 7×24 节律卡片（相位级演进）
- Math-OCR 本地模型（Texify 量化 / 小模型蒸馏）替代云端依赖（可选）
- 课堂会话"继续上次进度"记忆（IndexedDB，OpenMAIC generationParams 模式）

## 8. OpenMAIC 语义落地与实测（2026-08-25 补充，回应"以优秀 GitHub 项目取代"）

- **语义对齐**：`/api/classroom/sessions` 改为 OpenMAIC 式——**输入 `topic` 直接生成**（course_id 可选增强上下文，`m2_020` 的 course_id 置 nullable）；前端 DualView 增加主题输入，无课程也能开课。
- **实测（专用测试库 math_arena_wt，真实 mimo/spark 调用）**：
  - `POST {topic:"等比数列前n项和", slide_count:8}` → ready，**8 页全部落库**：导入/公式/特殊情形/例题×2/易错/变式/小结（含 LaTeX 与旁白）
  - 修复 JSONB 同引用不落库 bug：`session.slides = list(slides)`（新 list 触发变更检测）
- **本会话发现的两处既有问题**（未修，见验收清单 §5）：课程预处理 BackgroundTasks 本机不执行；V4Layout 路由守卫竞态。
- **两套迁移链并存**：你的开发库跑 `om2_openmaic_*`（D:\math-arena 并行推进 OpenMAIC 接入），工作树跑 `m2_*/m3_*`——本次全部迁移在隔离测试库验证，未污染开发库。