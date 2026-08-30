# 高中数学学生端 AI 升级诊断与执行台账

日期：2026-08-29  
范围：`D:\math-arena\services\api`、`D:\frontend`、`D:\知识库`；参考实现位于 `D:\AI对话`。

## 1. 结论

当前产品的主要问题不是某一条提示词，而是四个质量边界没有被强制执行：

1. **问题事实边界缺失**：题图、题干、选项、已知条件、目标和点名没有先固化为不可变的 `ProblemContract`。后续解题、讲解和作图可分别理解题目，因而会彼此偏离。
2. **教学状态边界失效**：学生的回答没有被可靠地判为“正确、部分正确、误解、澄清问题、请求答案、跑题”。截图中的“有影响／因为导数为零可以取到极值／难道不对吗”被错误地拉回同一问，说明状态机没有以已确认的当前断言和学生意图为唯一事实源。
3. **图形真实性边界尚未闭合**：现有图形校验大多验证“生成的坐标与自己声称的关系是否自洽”，不能证明它来自原题。候选文件 `v6_engine.py`/`v7_engine.py` 仍含默认函数或默认立体图逻辑，但本轮追踪未发现生产课堂路由引用它们；生产路由已改为条件不足时不渲染。真正缺失的是原题合同、图形构造和渲染验证三者的版本绑定。
4. **失败状态边界失效**：运行日志显示课堂幻灯片生成出现 `Single '}' encountered in format string` 后，系统仍将 8 页会话写成 `ready`。这是把模型失败转换为“看似完成”的降级内容的直接证据，必须优先修复。

“不再出现对话问题”不能诚实地承诺为绝对零错误；可承诺的是：没有通过题目合同、数学验证、证据充分性和端到端回归的内容，不能以“已完成、正确、原题图”名义呈现给学生。

## 2. 截图审查

### 2.1 对话与引导质量

极限选择题的最终解析本身正确：为使 `x→1` 时分式极限存在，分子在 `x=1` 处也必须为零，得到 `a=-1`；约去后极限为 `3`，故选择 D。

但教学过程存在明显质量问题：

- 学生回答“有影响”时，教师应先确认这是一条**部分正确的观察**，再要求补充“分母趋零后，为避免比值发散，分子须满足什么条件”。
- 学生说“因为导数为零可以取到极值”时，系统应先明确指出：这是把“函数在点处取极值”的导数条件误迁移到了“分式极限存在”；两者不是同一判断对象。现有回复直接说“这个话题先放一放，回到题目上来”，既没有纠错，也没有保存学生误解。
- 学生追问“难道不对吗”后，系统重复同一句回退话术，构成可复现的答非所问/循环。它不应继续追问原问题，而应给出一个最小反例或要求辨别“导数、分母、分子”三者哪个与本题条件直接相关。
- “第 5 步/共 5 步”由消息数量推断而非由已验证教学状态生成，因而既会误导学习进度，也会加剧“形式上走完、实际上未理解”的体验。

### 2.2 UI 与课堂历史

- 三栏布局在 1920px 桌面上给中间消息区留下过大的空白；固定输入框、滚动消息区和页面滚动同时存在，导致题卡被截断、回到底部按钮悬浮在内容之上。
- 题卡、对话进度、错误提示与输入区的视觉权重相互竞争；学生看不到“当前在解决什么、下一步要做什么、可以回到哪一节课”。
- 截图没有课堂目录、已完成课程、可恢复位置、来源题图或学习笔记入口。现有代码已出现 `ConversationSidebar`、消息分页和课堂 session/progress 接口，但这些属于工作区未提交的修复候选，尚未被证明已在学生体验中真正上线。
- 所有历史必须以“课程/题目卡片”而不是纯聊天标题呈现：来源题图缩略图、知识点、当前步骤、验证状态、最后学习时间、继续学习按钮、收藏/错题/笔记链接。

### 2.3 动态图像

两道图像题分别要求：

- 椭圆焦点三角形及内心轨迹：需保留椭圆方程、焦点、动点、内心和轨迹/观察目标，不能只画通用椭圆。
- 立体几何二面角题：需保留 A–E 点名、平面垂直、平行四边形关系、虚实线和要证明/计算的对象；立体转动必须不改变原题关系。

现有 `geogebra_figure.py` 有命令白名单、题型 profile、2D/3D 判别及图片 data-URI 输入；`visual_spec.py` 有函数采样和坐标图形；前端已有 Three.js 组件。这些是可复用基础，而非完成的视觉教学系统。生产 `stage_router.py` 现已在缺少可验证图形条件时改为“未渲染图形，请补充条件或原题图片”；但候选 V6/V7 引擎的默认图逻辑必须在接入前删除或隔离，任何概念示意也必须显式标注且不得冒充原题图。

## 3. 已核对的证据

| 证据 | 结果 | 含义 |
| --- | --- | --- |
| 截图 1–6 | 已人工审查 | 导航、状态、教学对话和长页面排版均有问题。 |
| 截图 7–8 | 已人工审查 | 可用作椭圆/立体几何的视觉忠实度验收输入。 |
| `backend.out.log`（2026-08-27） | 实测 | 多次 `classroom_slide_llm_failed: Single '}' encountered in format string` 后仍记录 `classroom_session_ready ... slides=8`。 |
| 核心课堂测试 | 68 passed | `test_dual_teacher_math.py`、`test_classroom_figure.py`、`test_classroom_openmaic_contract.py` 通过，证明现有候选代码的部分合同有效。 |
| 历史/RAG 集成测试 | 未完成 | 测试库 schema 重建等待超过 30 秒，已停止仅用于测试的进程；需在无并发测试锁时重跑。 |
| Agentic-RAG 参考测试 | 53 passed | `D:\AI对话\agentic-rag` 的充分性、冲突、引用和迭代检索契约可作为复用模板。 |
| Agent Ready | 不可扫描 | 扫描器拒绝私有地址 `127.0.0.1`；待有可访问预览地址后再做站点可读性审查。 |

## 4. 外部项目学习与复用边界

以下仓库只学习架构和测试方法，不直接复制未审查的业务代码：

| 项目 | 本地目录 | 复用点 |
| --- | --- | --- |
| awesome-geogebra-ai | `D:\AI对话\awesome-geogebra-ai` | 不可变数学模型、构造依赖图、类型化 GeoGebra 编译、参数滑块、绘制后对象检查、失败不展示残图。 |
| Math Phoenix | `D:\AI对话\math-phoenix` | 学生拍题→一次一问→卡住后提示→完成后小测与教师可见记录的产品闭环。 |
| MathTutorBench | `D:\AI对话\mathtutorbench` | 把解题正确性、苏格拉底提问、错误定位、错误纠正和脚手架质量分开评测。 |
| SocraticLM | `D:\AI对话\socraticlm-sparse` | 多轮教师—学生教学数据与逐步引导格式；采用稀疏克隆，避免下载不参与架构学习的大型训练资产。 |
| agentic-rag | `D:\AI对话\agentic-rag` | 检索计划、证据充分性、缺失事实回查、冲突呈现、逐主张引用和拒答降级。 |

## 5. 目标架构

```text
题图/文本/上下文
  → 多模态识别 + OCR 双通道
  → ProblemContract（不可变题干、选项、点名、条件、目标、置信度）
  → 合同核对（低置信字段让学生一键确认）
  → [解题器] 数学 IR → 符号/数值/几何验证 → SolutionPlan
  → [教学状态机] 学生意图 + 当前断言 + 掌握度 → 一个可回答的问题
  → [视觉编译器] 数学 IR/合同 → 构造图 → GeoGebra/Three 渲染 → 参数抽样验证
  → [知识检索] 仅在概念/方法/教材依据场景：路由→检索→充分性判定→引用回答
  → 会话、课程、错误概念、图形版本和验收轨迹持久化
```

### 5.1 解题与对话

- `Solver` 只生成结构化 `SolutionPlan`：题型、前提、每一步断言/理由、可验证计算、最终结果与可替代方法。
- `Verifier` 独立核验可计算部分；无法核验的证明性断言标为 `needs_review`，不可直接升格为“正确”。
- `Tutor` 不重新解题，只消费已核验步骤；每次回复必须结构化输出 `acknowledgement`、`diagnosis`、`next_action`、`one_question`、`state_transition`。
- `Judge` 先分类学生输入为 `correct/partial/misconception/clarification/off_topic/answer_request`；同一提示最多重复一次，第二次失败必须换支架（反例、选项、局部图或直接纠错），禁止空转。
- 全部步骤、判断理由、学生误解和答案查看行为写入 `TutorSession`，以便重开会话后无损恢复。

### 5.2 动态教学

- 使用支持视觉的模型（可评估 `mimo-v2.5-pro`）在**一次**请求内产出 OCR、题型、`ProblemContract`、数学语义和图形意图；低置信文字/点名先在 UI 中确认。
- 将图形输出改为 `ConstructionGraph`，由确定性编译器生成 GeoGebra/Three 图元；禁止把模型直接输出的命令当作最终事实。
- 每个动态图必须给出“本步观察什么、可调参数是什么、哪些对象会变化、哪些题设关系恒定”。
- 渲染后验证：对象依赖完整、关键点名存在、关系/长度/垂直/平行/二面角满足、滑块多点抽样不退化。失败不显示为原题图。
- 图像版本与题目合同 hash 绑定；编辑题目或重新 OCR 后必须新建版本，不能混用旧图。

### 5.3 知识库与 Agentic RAG

- 先清理 `D:\知识库`：保留人教教材、高考真题/解析、课程标准和经许可的高质量讲义；隔离明显无关的 LaTeX 工具源码/科研杂项，避免关键词污染。
- 每块必须有：学段、教材版本、章节、知识点、内容类型、年份、来源、许可证、页码/题号、解析可靠度和正文 hash。
- 只把 Agentic RAG 用于“概念、定义、方法依据、教材位置、类似题和学习建议”；精确求值、证明结论和选项答案必须走解题器/验证器，不能由检索拼凑。
- 默认最多两轮检索；第一轮混合检索+重排，第二轮只补足缺失事实。充分性不足、证据冲突或无来源时明确说“不足以确认”，并提示所需题目部分。

### 5.4 AI 管家

AI 管家只能从经过授权的学习记录、课堂进度、错题和掌握度工具读取信息；每项建议必须带数据来源与可执行动作。不要让管家替代解题器或自行编造学生学习历史。

## 6. 执行卡与验收条件

| 卡片 | 依赖 | 交付 | 通过条件 |
| --- | --- | --- | --- |
| P0：质量合同与金标集 | 无 | 三张截图题、极限题多轮反例、教材问答和历史恢复的版本化测试集 | 每项输入均有“题目事实、期望状态、禁止行为、验证方式”；答案只在测试机密夹具中，不写进业务逻辑。 |
| P1：失败不伪装完成 | P0 | 课堂生成的失败/降级状态、错误追踪和恢复入口 | 任何 slide 生成/格式化失败时 session 不得为 `ready`；UI 明示可重试和已成功页。 |
| P2：引导状态机 | P0 | typed judge/tutor 输出、误解分支、重复提示熔断、会话恢复 | 极限题中“导数为零可以取到极值”被明确纠正；“难道不对吗”不重复原话；同一会话重开后当前断言一致。 |
| P3：课程历史与 UI | P1、P2 | 课程目录、继续学习、来源题图、知识点、进度和响应式对话版式 | 1440/1920/1024 宽度无截断；输入区不遮挡消息；可找到并恢复过去课堂。 |
| P4：题图到动态构图 | P0 | `ProblemContract`、`ConstructionGraph`、编译/渲染验证、图形版本 | 椭圆与立体题能保留题图点名和关键关系；每个滑块在至少 5 个采样点通过关系检查；失败不展示伪原题图。 |
| P5：高中数学 Agentic RAG | P0 | 语料治理、路由、充分性、冲突和主张引用 | 教材问答引用可追溯；无关语料不被召回；证据不足时拒绝确定结论。 |
| P6：端到端评测与发布门禁 | P1–P5 | 真实后端链路、浏览器回归、仪表盘和发布清单 | 核心数学正确性、引导相关性、图形忠实度、历史恢复、检索引用和 UI 回归全部达阈值。 |

## 7. 量化门禁

- 可符号/数值核验的高考数学金标题：`100%` 计算一致；无法机检的证明题必须显示验证范围。
- 引导对话金标集：错误定位与下一问相关率 `≥95%`；同一问题无意义重复率 `0%`；未验证结论标为正确率 `0%`。
- 题图合同：关键文本/公式/点名字段逐字段准确率 `≥99%`；低置信字段不自动放行。
- 动态图：关键对象/关系完整率 `100%`；渲染后关系采样通过率 `100%`；禁止默认图冒充原题图。
- RAG：引用覆盖率 `100%`（所有教材/事实主张）；无关语料命中率 `<1%`；充分性不足时错误确定回答率 `0%`。
- 体验：三种目标视口的关键路径无溢出/遮挡；课堂历史恢复成功率 `100%`。

## 7.1 P2 补充根因证据（2026-08-29，本轮只读分析）

**可复现症状**：截图中学生先回答“因为导数为零可以取到极值”，再追问“难道不对吗”，系统第二次回复为“这个话题我们先放一放，回到这道题上来……”。

**已测得的执行路径**：

```text
DialogView / useChat（同一 conversation_id）
  → POST /api/agent/chat
  → active TutorSession 粘连（agent_router.py）
  → SocraticSolverExecutor._on_attempt
  → _judge（当前 verdict 仅有 correct / partial / wrong / new_problem / off_topic）
  → off_topic 分支
  → prompts.OFF_TOPIC_TEXT（截图中的逐字固定回复）
```

**证据与结论**：

- `services/api/app/gateway/agent_router.py:617-630`：活跃 `TutorSession` 时，后续学生消息跳过意图路由，稳定交给 `socratic_solver`。因此本例不能归因为前端丢失会话或普通聊天路由。
- `services/api/app/skills/socratic_solver/main.py:80,637-638`：判答枚举不含 `clarification` / `challenge_feedback`；一旦判为 `off_topic`，无条件输出 `OFF_TOPIC_TEXT`。
- `services/api/app/skills/socratic_solver/prompts.py:479-481`：该常量与截图中的重复回复一致。
- `services/api/tests/test_socratic_solver.py:749-760`：现有测试只验证真正闲聊“今天天气真好”会被拉回，未覆盖学生对上一轮反馈的质疑；该测试把症状路径当作了唯一合法的回退行为。
- `frontend/src/pages/student/DialogView.vue:177-183`：顶部“第 N 步 / 共 5 步”由助理消息数计算并封顶为 5，不读取后端 `socratic_progress` / `steps_count`，因此不是可信的教学状态。
- `frontend/src/composables/useChat.js:358-370`：前端连续发送会带上稳定的 `conversation_id`；这与后端粘连路径相互印证。

**根因判断（高置信）**：P2 的状态模型把“回答当前题步”和“质疑老师刚才的判断/要求解释”混为一类，缺少独立的澄清状态及其可审计上下文。因此依赖 LLM judge 的五分类会把短追问错误归为 `off_topic`，随后命中固定文本。此结论尚未进行真实模型调用复现；下一张实现卡应先以模拟 judge 输出写失败测试，证明 `clarification` 不再走 `OFF_TOPIC_TEXT`，再修改状态契约和呈现逻辑。

**非根因但必须随 P2 修复的体验误导**：当前步骤徽章是前端展示占位，不可用于恢复课堂或衡量掌握度；P3 应改为只消费会话持久化的 `current_step`、`steps_count` 与状态标签。

**2026-08-29 P2 工作卡：已完成（本地状态机合同）**：

- 在 `app/skills/socratic_solver/main.py` 中把 `clarification` 加入受控判答集；它走专用澄清教学分支，而非 `OFF_TOPIC_TEXT`。`clarification` 与真正 `off_topic` 均不计入学生的解题作答/本步尝试统计，避免质疑老师被误记为答错。
- 在 `prompts.py` 的 judge 契约中明确“围绕当前题步的追问、质疑、要求解释”为 `clarification`，并增加只解释本步依据、禁止泄露后续步骤、结尾只问一个核对问题的教学约束。
- 新增回归 `test_challenge_feedback_is_not_reclassified_as_off_topic`：MockLLM 返回 `clarification` 时，断言不出现固定跑题话术、进度卡仍为 `clarification`、步骤和提示等级不变化。该测试先在旧代码上失败（实际为 `partial`），再在修复后通过。
- 验证：目标红测与原有跑题/解析回归 `3 passed`；完整 `tests/test_socratic_solver.py` 为 `39 passed`。测试运行时仍会打印既有测试初始化的知识点外键警告，但没有使本测试文件失败。

**尚未完成的 P2 验收**：没有发起真实模型调用，因此尚未量化真实模型把“难道不对吗”判为 `clarification` 的准确率；下一次仅在获得模型调用授权后，才可用匿名化金标对话做离线评测。当前修复保证的是模型一旦给出该受控 verdict，状态机不会再将其错误回退为跑题。

## 7.2 P3 课堂历史与续学证据（2026-08-29，本轮只读分析）

**已实现且可复用的底座**：

- `services/api/app/models/classroom.py:41-59` 已持久化来源、页码进度、笔记、问答摘要、验证结果、知识点、内容版本与软删除。
- `services/api/app/domains/classroom/stage_router.py:2119-2181` 已提供按状态、来源、知识点、日期筛选的课堂列表；详情接口会返回 slides、进度、笔记和问答摘要。
- `frontend/src/pages/student/DualView.vue:635-663` 可从课堂详情恢复 `slide_index` 与笔记，并进入播放器；`747-766` 会对进度和笔记做防抖持久化。
- `services/api/tests/test_classroom_history.py` 已覆盖来源、软删除、进度、笔记、问答追加与课堂复制等接口合同；此前集成运行因测试库 schema 锁等待而未完成，不能据此宣称端到端已通过。

**学生端仍未闭环的缺口**：

1. `DualView.vue:611` 把失败课堂从“最近课堂”中静默排除，学生容易看不到失败原因和恢复入口；这与 P1 的“失败不伪装完成”要求冲突。
2. `DualView.vue:754-765,891` 对进度、笔记、问答写入失败均静默吞掉。网络中断后学生仍会以为已保存，回到课堂后才发现位置或笔记丢失。
3. 历史列表只有标题、页数、状态和进度；来源详情虽可展开，但没有题图缩略图、知识点可视标签、验证状态说明、未保存状态与“继续到第 N 页”的主导信息。
4. 课堂内 AI 助教问答另起普通 chat 会话，只用一段自然语言注入“我在第 N 页”。它不带 `session_id`、不可查询 `qa_summary` 以恢复连续问答，也不能把错误概念可靠写回该课堂。
5. 失败课的“重新生成”仅传回标题、页数、模式（`DualView.vue:664-675`），未带回来源引用或不可变题目合同；对拍题课堂会丢失原件绑定并可能生成另一堂内容。

**结论（高置信）**：系统已经有“保存”和“打开”的技术能力，但还没有可证明的学生课堂恢复产品闭环。P3 不应重造历史存储，而应在现有会话模型上补：写入确认/离线待同步、来源合同传递、课堂专属问答上下文、失败态可见及按知识点/验证状态检索的历史卡片。

**2026-08-29 P3 工作卡 A：已完成（隔离后端树）**：为不混入主工作区的未提交课堂候选改动，已在 `D:\codex-worktrees\math-arena-student-ai-upgrade` 的 `codex/student-ai-upgrade` 分支实施并验证最小“继续学习”闭环：

- 发现并修复基线模型注册缺口：`ClassroomSession` 未被 `app.models` 导入，干净数据库不会建 `classroom_sessions` 表。
- 新增会话 `progress` JSON 字段和 `m2_021_classroom_session_progress` 迁移；新增属主校验、页码越界拒绝的 `PATCH /api/classroom/sessions/{id}/progress`。
- 会话详情与历史列表都返回同一 `progress`，无课程的自由主题课堂不再以空主键查询 `Course`。
- 新增真实 HTTP 回归：学生更新到第 5 页后，详情和列表均恢复 `{slide_index: 5}`。旧基线先失败为 404；修复后通过。`alembic heads` 显示新迁移为唯一 head；联合 `test_classroom_history_progress.py` 与 `test_socratic_solver.py` 为 `39 passed`。

**P3 下一卡**：在前端隔离树中为进度/笔记写入加入“保存中、已保存、待重试”可视状态，禁止静默 catch；随后将失败课堂置入最近课堂，保留其重试入口与来源合同。前端主工作区当前含用户未提交改动，不能原地修改。

## 7.3 P4 动态图真实性证据（2026-08-29，本轮只读分析）

**生产链路（实测源码）**：`stage_router._gen_slide_content` → `_materialize_blocks` → 页级 `verify_slide` → 仅验证通过且有教材证据时才附加 GeoGebra 块。几何数据不完整时，`stage_router.py:1493-1500` 改为提示“未渲染图形”，而 `_programmatic_patch_blocks` 明确不补造默认图。

**已纠正的旧判断**：`v6_engine.py` 和 `v7_engine.py` 都含通用椭圆、默认多面体/函数图的候选实现，但 `rg` 未发现 `stage_router.py` 或其他生产代码导入其 `run_postprocess_pipeline`。它们不能作为当前线上默认图的证据；接入前仍必须移除默认图成功回退或标为概念示意。

**尚未满足原题忠实度的事实**：

1. 课堂 slide 只有 `source_conditions` 与 `source_ref` 元数据，没有不可变 `ProblemContract`、题图 hash、点名清单或目标关系清单；因此无法证明椭圆题的 `F1/F2/M/I`、或立体题的 `A–E`、虚实线、垂直/平行/二面角来自同一原题版本。
2. `stage_router.py:1569-1608` 只在数学验证与教材证据均通过后添加 GeoGebra，但附加的 `visual_verification` 仍为 `needs_review`；它验证命令安全与教材依据，尚未验证图形满足原题的关系。
3. `DualView.vue:324-335` 对普通 `geometry` 块无来源/合同状态展示，直接交给 Three.js 渲染；GeoGebra 才显示复核原因，视觉可信度提示不一致。
4. 现有图形测试主要测渲染输入规范化、数值自洽和安全过滤；未测试截图 7、8 所要求的命名、题设关系、原题版本 hash 和渲染后多点抽样的完整闭环。

**下一张实施卡的失败测试**：给定一份题图合同，若图形缺少指定点名或关系、合同 hash 不匹配、或滑块采样出现退化，则不得标记为“原题动态图”；只能显示“待核对”或“概念示意”。这是一条通用合同测试，不写入任何截图题的标准答案。

**本轮新发现的可复现红灯**：运行 `tests/test_classroom_rag_orchestrator.py` 的无模型子集时，`test_right_trapezoid_pyramid_witness_uses_confirmed_lengths_not_gold_values` 失败。坐标、AD/BC/CD/SA 四条长度和 ADC/BCD/SAD 三个直角均已通过；只有 `apex_height=5` 失败，验证器实际将底面点 `D`（横坐标为 6）猜作顶点，算出“高度”6。

**根因与最小修复合同（高置信）**：`math_verifier._verify_declared_metrics` 的 `apex_height` 目前仅是数值，采用“所有坐标分量最大者减最小者”的猜测逻辑；它没有顶点名或底面平面，数学语义本身不充分。`build_right_trapezoid_pyramid_coordinate_witness` 则已知顶点为 `S`、底面为 `ABCD`，但无法传给验证器。下一张 P4 实施卡必须先增加失败测试，规定高度断言使用显式 `{value, apex, base_plane}`，并由点到平面的距离独立计算；旧的裸数值只能降级为 `needs_review`，不能以坐标轴猜测替代。该改动涉及现有未提交代码，尚未写入，以免覆盖用户工作。

**2026-08-29 自动卡执行结果**：已再次复现上述失败；最窄子集为 `14 passed, 1 failed`，失败项即高度见证测试，且失败原因与坐标最大值猜顶点一致。随后核对发现 `app/domains/classroom/math_verifier.py`、`app/domains/classroom/rag_orchestrator.py`、`tests/test_classroom_rag_orchestrator.py` 和 `tests/test_classroom_openmaic_contract.py` 均为当前仓库未跟踪文件，不能安全判定归属。因此本卡**不修改这些文件**，避免把新的契约实现混入用户已有候选改动；它不能标记为完成。要完成 P4，需要用户先将该候选工作明确交由本升级任务处理，或提供隔离后的干净工作树。下一张自动卡改回 P2：在已跟踪的 Socratic Solver 路径上核对可安全修改范围，并先写“质疑反馈不得走跑题回退”的失败测试。

## 7.4 P5 Agentic RAG 与语料边界证据（2026-08-29，本轮只读分析）

**已存在的可靠底座**：

- `services/api/scripts/import_pep_textbooks.py:1-32,88-156` 并不会递归导入整个 `D:\知识库`。它只读取 `AC切片\processed` 下五个固定白名单批次，且要求“人教 A 版 2019、学生教材、非教师用书”；落库时写入 `scope=student`、`corpus_class=student_textbook`、教材册/章节和稳定知识点元数据。
- `services/api/tests/test_import_pep_textbooks.py:36-61,175-` 已验证教师用书和其他版本不能混入该学生教材批次，且章节元数据会被保留。这是可复用的语料准入基线。
- `services/api/app/kernel/rag.py:101-315` 已实现查询改写、向量/全文/知识点三路并行召回、RRF、重排和相关性拒答；`rag_orchestrator.py:218-317` 又把课堂检索限制为 `scope=student`、`content_type=textbook`，并在题图条件未确认时阻断检索。

**必须分清的风险边界**：本机 `D:\知识库` 共有约 13,634 个文件，其中约 11,441 个为 JPG，另有大量 `.tex/.sty/.cls/.dtx`；`类E已处理` 的抽样包含 LaTeX 宏包源码。它们是原始目录内的明显非教材资产，**不是**“已进入学生教材索引”的证据。风险在于未来任何“整目录通用导入”或人工上传路径绕过上述白名单时造成关键词污染，因此必须在导入层维持默认拒绝、显式来源白名单和隔离审计，而不能靠检索相关性事后补救。

**当前尚不是 Agentic RAG 的原因**：

1. `RAGResult` 仅包含 `chunks/answerable/refuse_reason/rewritten_query`；`answerable` 由 top-1 相关性门槛决定，不能表达“本回答的每个事实是否均有证据”。
2. `retrieve_classroom_evidence` 只调用一次 `rag.retrieve` 后格式化少量引用；没有按待回答主张拆分缺失事实、第二轮定向检索、证据冲突检测或“充分/不足/冲突”的结构化决定。
3. `qa_rag/main.py` 虽提示模型“资料未覆盖就说明无法确认”，但直接把一次检索的片段交给生成器，引用只在流式生成完成后按 chunk 整体附上；没有可机检的“句子/主张 → citation”映射。因此提示词不能代替证据充分性门禁。

**P5 下一张失败测试（先红后绿）**：构造不依赖真实模型的假检索结果，要求：（a）需要两个独立教材事实、却只返回一个事实时，编排层输出 `insufficient` 并不得生成确定结论；（b）两个已标注来源的片段互相冲突时，输出 `conflict` 并展示冲突出处；（c）来源不具备 `student_textbook` 白名单元数据时，即使词面相关也不得成为学生教材回答证据；（d）每个可呈现的教材事实都必须带稳定 chunk id 与册/章/节引用。通过后再接入最多一轮“补缺事实”检索，始终不把精确求值/证明正确性委托给 RAG。

**未解决风险**：当前测试库重建曾被 schema 锁阻塞，且未发起真实 embedding/云知识库/模型调用；因此上述结论只覆盖源码合同与本地语料目录，不声称线上索引内容、召回率或模型回答质量已经验收。

## 8. 当前禁止事项

- 不把截图中的标准答案写成业务分支或提示词特例；所有测试必须通过通用合同、验证器和状态机。
- 不在未通过题图忠实度校验时输出“根据原题绘制”。
- 不让任何单个 LLM 同时充当 OCR、求解器、裁判、教学者和最终真实性判定。
- 不用低相关/无来源知识块给教材事实背书。
- 不覆盖当前两个仓库的未提交改动；每张执行卡必须先确认文件归属和冲突范围。

## 9. 自动推进

已创建“高中数学学生端升级推进”自动任务：按平台允许的最高频率每小时完成一张可验证工作卡，写回本台账，不部署、不提交、不接触密钥。下一张卡：P3 课堂历史恢复，先为“失败课堂可见、写入失败不静默、重试保留来源合同”选取一个可安全隔离的最小故障路径并写红测。涉及真实模型调用、密钥或公开部署时必须暂停并请求授权。

**2026-08-29 P3 工作卡 B：已完成（隔离前端树）**：在 `D:\codex-worktrees\frontend-student-ai-upgrade` 的 `codex/student-ai-upgrade` 分支实现学生翻页进度的可见、可恢复写入状态，未触碰主前端工作区的未提交改动。

- 新增 `useClassroomProgress`：翻页后防抖保存；服务端拒绝/网络失败时保留同一 `{sessionId, slideIndex}` 待重试；只有确认同一请求成功后才显示“已保存”。
- `DualView.vue` 使用该状态恢复详情中合法的 `progress.slide_index`，显示“保存中 / 已保存 / 保存失败，待重试”，并提供“重试保存”；离开课堂时会立即触发最后一个待写入页码的 `flush`，不再主动取消它。
- 失败测试先新增“视图销毁前必须 flush 最后一个排队页码”，旧实现报 `progress.flush is not a function`；补齐后 `test/student/classroomProgress.test.ts` 为 `2 passed`，并完成生产构建（`306 modules transformed`）。
- 本地真实界面检查**未通过、不能计为验收证据**：预览进程在执行环境命令结束后被回收，浏览器两次得到 `ERR_CONNECTION_REFUSED`。这不是产品界面断言失败，也不替代后续已登录真实路径检查。

**P3 下一卡**：服务端新增课程笔记持久化接口与端到端恢复回归；随后把前端 `saveNotes` 从 localStorage-only 升级为同样的确认/重试写入。当前笔记仍只落在浏览器，不能声称笔记跨设备恢复已完成。

**自动任务状态修正**：用户已要求停止定时自动任务，`automation-4` 已删除；本台账继续作为人工连续推进记录，不会再按既有自动日程唤醒。

**2026-08-29 P3 工作卡 C：已完成（隔离后端树）**：在 `D:\codex-worktrees\math-arena-student-ai-upgrade` 实现课堂笔记的服务端恢复合同。

- 先新增真实 HTTP 失败测试：学生向 `/api/classroom/sessions/{id}/notes` 写入“笔记文本 + 所在页”，必须能在同一课堂详情恢复。旧代码得到 `404`，证明此前笔记没有服务端路径。
- 新增 `notes` JSON 字段及 `m2_022_classroom_session_notes` 迁移；笔记接口实施属主校验、4000 字上限和课堂页码越界拒绝。详情返回笔记，因此跨设备重新打开课堂时具备读取契约。
- 首次实现暴露身份对象兼容性问题：新接口错误取用 `user["id"]`，旧登录路径只提供 `sub`，测试实际报 `KeyError: 'id'`；已统一到现有课堂接口的 `sub` 合同。
- 验证：`test_classroom_history_progress.py` 为 `2 passed`；`alembic heads` 仅为 `m2_022_classroom_session_notes`。测试环境仍打印既有知识点外键初始化告警，未令本卡失败。

**P3 下一卡**：前端笔记保存改用该接口并显示“保存中/失败待重试”；然后补历史列表中失败课堂可见与来源合同重试。尚未运行数据库迁移、未部署、未调用真实模型。

**2026-08-29 P3 工作卡 D：已完成（隔离前端树）**：笔记编辑已从 localStorage-only 改为课堂专属服务端同步。

- 新增 `useClassroomNotes`，与进度保存分离，但同样保存精确的课堂 id、笔记内容和页码；失败时保留 payload，显示“笔记保存失败，待重试”，成功确认后才显示“笔记已保存”。
- `DualView.vue` 从课堂详情回填 `notes.content`，编辑后调用 `/notes`；页面卸载时 flush 待写笔记。原先的浏览器本地存储、无痕模式静默忽略和“浏览器本地保存”提示均已移除。
- 失败测试先因缺少 composable 不能解析而失败；实现后笔记 + 进度最窄测试为 `3 passed`，生产构建成功（307 modules）。构建仍有既有 router 静态/动态混用警告，未影响产物生成。

**P3 下一卡**：调整课堂加载策略，让失败课堂不会被 `status === ready` 静默过滤，并且把重试与来源合同绑定；现有干净基线缺少来源不可变合同字段，这部分需先补合同读写测试，不能靠标题重建。

**2026-08-29 P3 工作卡 E：已完成（隔离前端树）**：失败课堂不再被学生端加载逻辑静默遗忘。

- 新增纯选择合同 `selectSessionForRecovery`：选中课程优先；同一课程的可续学课堂优先于失败课堂；若没有可续学记录，最近失败课堂仍被选择并展示原因。
- 失败课堂详情现在进入明确的失败状态，而不是退回到“尚未生成”。原先会按当前课程/主题重新生成的按钮已改为“重新配置课堂”：干净基线没有不可变来源合同，不能把重建误称为对原课堂的安全重试。
- 失败测试先因选择器缺失而失败；实现后历史选择、进度保存和笔记同步测试共 `5 passed`，生产构建成功（308 modules）。

**P3 下一卡**：后端为课堂建立不可变来源合同，前端只在合同完整时开放“按原来源重试”；这也是后续题图→动态讲解真实性链路的前置条件。

**2026-08-29 P3 工作卡 F：已完成（隔离后端 + 前端树）**：创建与重试课堂的来源不再只依赖易变标题。

- 后端新增版本化 `source_contract`：规范化课程 id/课程标题、主题与补充要求，计算 canonical JSON 的 `input_sha256`，在创建时落库，列表、详情和创建响应均返回。它只声明实际持有的来源；文字/课程来源不能冒充题图来源。
- 来源合同失败测试先因模块不存在而失败；实现后课程和主题两类合同均验证版本、规范化输入、创建时课程身份与 64 位指纹。其与历史恢复测试联合为 `4 passed`，迁移 head 为 `m2_023_classroom_source_contract`，`git diff --check` 无空白错误。
- 前端仅在合同版本、输入指纹、来源类型与必要字段均完整时显示“按原来源重新生成”；重试请求从合同重建课程/主题/补充要求，合同不全时拒绝猜测并回到重新配置。相应前端回归共 `7 passed`，生产构建通过（309 modules）。

**范围与风险**：该合同还没有题图文件 hash、OCR 文字、实体清单或几何关系，因此尚不能证明截图题的“按原题重试”或动态图真实性；这些字段属于 P4 的题图合同，必须在不调用真实多模态模型的前提下先做结构与验证器合同。

**P3 后续**：真实已登录 UI 路径仍待可持久本地服务/测试环境执行；数据库迁移未运行、未部署。P3 的可恢复数据合同已具备进度、笔记、失败可见与文字/课程来源重试，接下来进入 P4 的题图合同。

**2026-08-29 P4 工作卡 A：已完成（隔离后端树）**：建立了题图/动态图之间的最小确定性覆盖门禁。

- 新增 `validate_diagram_contract(problem_contract, diagram_contract)`：只有来源 hash 完全一致、题目合同中的每个实体和每个关系 id 都被图形规格显式表示时，状态才为 `verified`；否则一律为 `needs_review`，并返回缺失实体/关系。
- 失败测试先因模块不存在而失败；覆盖两个通用事实：焦点三角形示意漏掉 `I` 时不能标称原题图，立体几何示意只有同时覆盖 `A–E` 与已声明的平面垂直/线垂直关系时才可验证。它们只测合同，不嵌入任何原题答案。
- 验证：题图合同、来源合同、课堂进度/笔记共 `6 passed`；`git diff --check` 无空白错误（仅有既有 LF/CRLF 提示）。

**P4 下一卡**：把该门禁接入图形 block 的生成/渲染契约：没有 `verified` 结果时只标“概念示意/待核对”，不能显示“按原题绘制”；随后再增加点到平面高度的显式见证验证。当前卡尚未调用 Mimo、OCR 或任何真实模型。

**2026-08-29 P4 工作卡 B：已完成（隔离后端 + 前端树）**：题图真实性状态已进入图形事件、历史重放与学生可见标签。

- `figure_block` 现在默认写入 `visual_verification={status: conceptual}`；只有同时提供题图合同和图形合同才会调用确定性验证器。漏点/漏关系/来源不一致输出 `needs_review`，不会以“原题图”通行。
- `MathFigure.vue` 将状态明确渲染为“概念示意 / 题图待核对 / 已核对原题关系”。旧消息没有合同也会显示“概念示意”，避免因字段缺失获得不实背书。
- 回归先暴露历史重放仍按旧载荷断言；更新合同后 `test_figure_block.py`、题图合同、课堂来源和恢复测试共 `21 passed`。前端状态映射与既有课堂测试共 `10 passed`，构建成功（310 modules）。

**P4 下一卡**：为立体几何 `apex_height` 引入 `{value, apex, base_plane}` 显式见证，并按点到平面距离独立验算；旧裸数值不再猜测坐标轴高度。

**P4 高度见证实施边界（2026-08-29）**：已再次只读定位高度误判代码：主仓库的 `app/domains/classroom/math_verifier.py` 与 `rag_orchestrator.py` 都是用户当前未跟踪候选文件；测试也依赖这两者。将它们直接复制到隔离树或原地改写会混入/覆盖用户尚未提交的工作，因此本轮不做该写入。此前复现的错误与修复合同仍有效：裸 `apex_height` 按坐标最大分量猜顶点是错误的；应改为显式 `{value, apex, base_plane}`，按点到平面距离独立验证。该项留在 P4 待接入列表，不标记完成。

**2026-08-29 P5 工作卡 A：已完成（隔离后端树）**：为高中数学知识库补入了不依赖模型的“证据是否足够回答”判定底座，复用调研项目的“计划—证据—充分性—拒答”分层思想，但未复制其业务代码。

- 新增 `app/kernel/rag_evidence.py`：上游可用结构化题目/知识事实计划声明每个必须事实的关键词和可能冲突值；该模块只接受 `textbook`（兼容现有文档类型）或 `student_textbook` 切片作为学生教材证据，输出 `sufficient / insufficient / conflicting / unanswerable`，且仅 `sufficient` 才允许确定性教材回答。
- 每一条可展示引用固定保留 `chunk_id`、文档 id、教材名、来源类型、册（chapter）与节（section）；引用按 chunk id 稳定排序。教师笔记、网页和模型生成物即使词面匹配也不能独自作为学生端教材依据。
- 失败测试先因模块不存在而在收集阶段失败；实现后四个通用回归通过：两个独立知识事实只覆盖一个时为 `insufficient`，教材内容冲突时为 `conflicting`，`teacher_note` 不能满足教材事实，引用可回到稳定切片及册/节。验证：`tests/test_rag_evidence_sufficiency.py` 为 `4 passed`；既有 `RAGResult/ScoredChunk` 数据合同回归为 `2 passed`。两次测试仍打印既有知识点外键初始化告警，但未导致失败。

**P5 下一卡**：在保持一次检索行为不变的前提下，给 `ScoredChunk` 补齐从 `KnowledgeDoc.meta` 透传的教材范围/章/节来源元数据，并提供显式的“结构化事实计划 → 证据评估”接线；只有调用方提供必须事实时才启用新门禁，不能用关键词猜测把正常问答误拦截。随后才考虑最多一轮针对缺失事实的定向检索，并为其设置不调用模型的上限和审计字段。

**P5 未解决风险**：当前线上 RAG 调用尚未生成结构化“必须事实”计划，故新模块还未改变任何真实回答路径；这是一项有意的安全边界，不应据此声称幻觉已消除。接线前仍需验证 `KnowledgeDoc.meta` 的实际章/节字段，且真实 embedding、云知识库和模型调用均未获授权、未执行。

**2026-08-29 P5 工作卡 B：已完成（隔离后端树）**：已将“学生教材”从宽泛的文件类型进一步收紧为导入白名单身份。

- 根因：现有 `KnowledgeDoc.source_type=textbook` 不足以区分学生教材与教师教材；可信导入器实际使用 `meta.corpus_class=student_textbook` 作为白名单身份。
- 失败测试先将 `corpus_class` 传入证据片段，旧数据契约报 `unexpected keyword argument`；实现后 `EvidenceSnippet/EvidenceCitation` 都携带该字段，只有 `source_type in {textbook, student_textbook}` **且** `corpus_class=student_textbook` 的切片才能覆盖学生端事实。
- 验证：证据充分性回归扩展为 `5 passed`，包含“教师教材即使也是 textbook 也必须拒绝”；既有 RAG 数据类回归 `2 passed`；`git diff --check` 无空白错误（仅既有 LF/CRLF 提示）。

**P5 下一卡**：隔离基线的 `Chunk` 模型没有切片 `meta` 字段，而可信教材导入器需要其保存 section/source_chunk_id。先为 `Chunk.meta` 建立模型和迁移合同，再在三路检索中透传文档 `corpus_class/volume` 与切片 `section` 到 `ScoredChunk`；不运行迁移、不导入知识库、不发起 embedding 请求。

**2026-08-29 P5 工作卡 C：已完成（隔离后端树）**：教材出处已从数据库模型通过检索结果连续透传到证据判定输入。

- 根因：隔离基线 `Chunk` 缺少 `meta` JSONB，而可信导入器需要在切片保存 `section/subsection/source_chunk_id`；原 `ScoredChunk` 也没有来源类型、白名单身份、册或节，因此无法构造真实的可审计教材证据。
- 新增 `chunks.meta` 模型字段与 `m2_024_chunk_provenance_metadata` 迁移（唯一 Alembic head）。向量、全文和知识点三路检索均读取文档的 `source_type/meta` 与切片 `meta`，并将 `corpus_class`、`volume`、`section` 传到 `ScoredChunk`；云知识库被明确标为非学生教材来源。
- `ScoredChunk.to_evidence_snippet()` 现在将稳定切片 id、教材名、文档来源、白名单身份、册和节转换为 P5 门禁所需的证据对象。缺失 metadata 保持为空，绝不默认填成学生教材。
- 失败测试先暴露 `Chunk.meta_` 与 `ScoredChunk` 来源字段均不存在；实现后来源、充分性与转换回归为 `8 passed`，云知识库 RRF 兼容回归 `1 passed`，`alembic heads` 为 `m2_024_chunk_provenance_metadata`。未运行迁移，未读取/导入 `D:\知识库` 内容，未调用 embedding 或模型。

**P5 下一卡**：将充分性判定作为 `RAGPipeline.retrieve` 的**显式可选**输入/输出：只有课堂的不可变题目合同或其他调用方提供 `EvidenceRequirement` 时，才在相关性门槛后附加 `sufficient/insufficient/conflicting/unanswerable` 门禁；没有事实计划的既有普通问答保持行为不变。为不足或冲突状态写真实 RAG 返回回归，再决定前端如何解释拒答。

**2026-08-29 P5 工作卡 D：已完成（隔离后端树）**：证据充分性已成为 RAG 管线的可选、可审计门禁，而非仅停留在独立工具。

- `RAGPipeline.retrieve` 新增可选 `evidence_requirements`；常规调用未提供计划时返回 `evidence_assessment=None`，保持原相关性检索和生成路径不变。
- 调用方提供结构化必须事实时，管线在原有相关性门槛通过后再评估所有 `ScoredChunk` 的学生教材证据。只有 `sufficient` 才继续 `answerable=True`；部分覆盖、来源不合格、或冲突时，返回 `answerable=False` 和 `evidence_insufficient / evidence_unanswerable / evidence_conflicting` 原因，连同结构化 assessment 供课堂界面解释。
- 失败测试先因 `_assess_evidence_gate` 缺失而失败；实现后覆盖“部分覆盖拒答”和“无事实计划完全兼容”。联合证据、来源、云检索完整回归为 `31 passed`，迁移 head 仍唯一为 `m2_024_chunk_provenance_metadata`，无空白错误。

**P5 下一卡**：为课堂/题图合同增加可选的、由已确认知识点或人工审核生成的 `evidence_requirements` 字段，并将它作为参数传给 RAG；不允许以 LLM 自由生成的关键词计划直接开启硬拒答。由于当前普通 `qa_rag` 没有传此参数，它不会错误触发“证据不足后又走通用模型”的降级路径。课堂接线后还需为该特殊拒答增加不调用模型的学生提示，防止未来误降级。

**2026-08-29 跨卡回归证据**：已在隔离后端树运行 Socratic 状态机、课堂历史进度/笔记、来源合同、图形块与题图合同、RAG 充分性/来源/门禁的联合最窄集合，结果为 `69 passed in 15.07s`。测试启动仍报告既有知识点 parent FK 初始化告警，但没有失败项。所有变更仍未提交、未部署、未执行迁移或真实模型调用；工作树仅含本升级任务列出的修改和新增文件，主仓库用户改动未被覆盖。

**2026-08-29 P4 工作卡 C：已完成（隔离后端树）**：立体几何的“顶点到底面高度”已具备独立、显式的数学见证合同。

- 新增 `geometry_witness.verify_apex_height_witness`：只接受 `{value, apex, base_plane:[A,B,C]}`，以叉积得到底面法向量，并用点到平面距离独立验算。底面三点共线、坐标无效、顶点属于底面、数值不一致都会返回 `needs_review`。
- 裸 `apex_height: 5` 不再猜测最高坐标或顶点，固定返回 `explicit_apex_and_base_plane_required`。这直接消除了此前将底面点 D 的横坐标 6 误作高度、而真实顶点 S 到底面距离为 5 的错误模式。
- 失败测试先因模块不存在而收集失败；实现后高度见证、题图合同和图形块回归为 `19 passed`，无空白错误（仅既有 LF/CRLF 提示）。该模块没有改写主仓库未跟踪的 `math_verifier.py/rag_orchestrator.py`；接线必须等这些候选文件明确归属或迁入同一隔离树。

**P4 下一卡**：把显式高度见证纳入隔离图形 block 的 `visual_verification`，使携带裸高度断言的原题图只能显示“题图待核对”，携带通过见证的图可保留“已核对原题关系”。随后再处理题目图片的不可变 OCR/原图 hash 合同；真实 Mimo/OCR 调用仍需授权。

**2026-08-29 P4 工作卡 D：已完成（隔离后端树）**：高度见证已成为图形事件最终真实性标签的一部分。

- `FigureBlock` 新增可选 `geometry_witness`。当图形具有题目/图形合同且高度见证存在时，事件将记录 `visual_verification.height_witness`；该见证不是 `verified` 时，最终状态强制降为 `needs_review` 并返回可解释原因。
- 新增回归首先复现了原错误：实体、关系与题目 hash 都匹配时，裸 `apex_height: 5` 会被标为 `verified`。接线后同一输入为 `needs_review / explicit_apex_and_base_plane_required`，不会再对学生暗示该图已按原题完全核对。
- 验证：`test_figure_block.py`、高度见证和题图合同共 `20 passed`；未改主仓库未跟踪验证器，未调用 OCR/Mimo 或任何真实模型。

**P4 下一卡**：题目截图进入课堂前，先建立“原图 hash + OCR/人工转写文本 hash + 结构化题目合同版本”的不可变输入记录；只有各 hash 一致的题图、教学图和检索事实计划才能互相引用。实际多模态 OCR 识别需要模型/密钥授权，本卡先只实现不依赖模型的合同校验和失败测试。

**2026-08-29 P4 工作卡 E：已完成（隔离后端树）**：题目图片、转写文本和结构化数学语义已获得统一的不可变来源指纹。

- 新增 `problem_input_contract`：对原图字节、OCR/人工审核转写、结构化语义合同分别计算 SHA-256，并将三者及版本 canonical JSON 合成为 `source_sha256`。该值可直接填入现有题图/动态图合同，形成同一来源链。
- 失败测试先因模块不存在而失败；当前回归证明原图、转写或语义任一变更都会导致 `needs_review`，其中改写 OCR 文本会明确返回 `transcription_sha256` 与 `source_sha256` 不匹配，不能复用原题的图形或知识检索结论。
- 验证：原图输入、题图合同、图形块和高度见证联合为 `22 passed`，未上传任何图片、未调用 Mimo/OCR/模型，未触碰主仓库的未跟踪多模态候选代码。

**P4 下一卡**：将通过审核的 `problem_input_contract.source_sha256` 作为课堂 `source_contract` 的可选 `problem_source_sha256`，并让重试和图形合同只引用该不变值；没有它的文字主题课堂继续明确标为概念示意。图像文件的实际存储/上传与 Mimo 识别需要另行授权。

**2026-08-29 P4 工作卡 F：已完成（隔离后端树）**：课堂来源合同已具备受控的题图来源绑定入口。

- 新增 `bind_verified_problem_source(source_contract, problem_input_contract, validation)`：只在字节/转写/语义合同验证状态为 `verified` 且来源 hash 合法时，才复制并重签课堂合同，写入 `problem_source_sha256`。接口不接收自由文本 hash，避免客户端未经服务端核验便冒充原题来源。
- 失败测试先因绑定函数缺失而无法导入；实现后确认绑定后的课堂合同携带正确题图来源、并拥有新的 input hash。来源、输入、题图、图形和高度见证联合回归为 `25 passed`。
- 该入口尚未暴露到学生创建课堂请求，因为目前没有独立、受控的图片上传→OCR/人工审核服务链；因此不会把客户端提供的任意 OCR/图片 hash 误当可信依据。没有题图来源的普通主题课堂仍必须保持“概念示意”标签。

**P4 下一卡**：实现受控的本地“上传结果/人工审核转写 → `problem_input_contract` → 课堂绑定”服务接口，并以真实文件 hash 但不调用模型的路径做 HTTP 回归；只有获得明确的模型与数据处理授权后，才把 Mimo 多模态 OCR 接入该接口。

**P4 文件链路复核（2026-08-29，只读）**：隔离基线的 `app/domains/files/router.py` 已有开发环境本地上传路径，上传时会同时校验长度和 `sha256(data) == File.sha256`，因此已上传图片可作为真实原图 hash 的受控凭据。另一方面，`POST /api/files/{id}/parse` 的 `question_photo` 现有实现会自动进入 RapidOCR、Mimo 文本规整与视觉模型候选路径（失败才落入人工复核）。本轮没有请求该端点，也没有读取/上传用户图片；但这说明题图合同接线前必须先为真实模型处理加显式授权闸门，不能把既有自动解析当作已获授权的 OCR 验收。

**下一张卡**：为 `question_photo` 解析请求增加显式、逐次的“允许模型处理图片”标记；未授权时直接进入人工审核/本地 hash 合同，不发起 RapidOCR、Mimo 或云视觉调用。测试必须 mock 全部解析器并证明调用数为 0。

**2026-08-29 P4 工作卡 G：已完成（隔离后端树）**：拍照题的真实模型处理已改为每次请求显式授权，默认不处理图片。

- `ParseRequest` 新增 `allow_model_processing=False`；只有 `purpose=question_photo` 且该字段显式为 `true` 才允许进入 OCR/Mimo/视觉模型链。该授权不会被 `chat_attach` 等其他用途复用。
- 未授权拍照题在路由层立即转为 `parsed/manual_photo_review`，记录 `model_processing_authorized=false`，且不创建后台解析任务。因此不会调用 RapidOCR、Mimo 或云视觉服务，也不会把原图发送到外部。
- 红测先因授权合同函数不存在而失败；实现后 3 项回归通过，其中直接调用端点断言 `BackgroundTasks.tasks == []`、文件状态为人工复核且数据库仅执行本地状态提交。未调用任何模型或网络服务。

**P4 下一卡**：在授权明确为 true 时，为 OCR/Mimo/视觉调用记录不可变题图来源与审核状态；在未授权人工审核路径中新增“已审核转写 + 结构化语义合同”受控保存，二者都必须再通过 `problem_input_contract` 后才能绑定课堂。真实模型测试仍需用户明确授权。

**2026-08-29 P4 工作卡 H：已完成（隔离后端树）**：已为课堂的人工审核路径建立“服务端已验证文件 hash”输入入口。

- `build_problem_input_contract_from_image_sha256` 只接受 64 位十六进制摘要，并与审核转写、结构化语义共同构建不可变来源合同。普通字节入口复用该函数；未来课堂端点只能从当前用户 `File.sha256` 调用它，而不接受客户端可写 hash 参数。
- 红测先因函数不存在而失败；实现后 6 项题图输入/授权回归通过。未读取文件内容、未执行上传、未调用 OCR、Mimo 或视觉服务。

**P4 下一卡**：在课堂会话端点新增“绑定已审核题图”的属主、图片类型和已上传状态检查：读取服务器 `File.sha256`、构建输入合同、重新签名课堂来源合同并返回给前端。以真实 HTTP 测试验证跨用户/非图片/未上传文件均不能绑定。

**2026-08-29 P4 工作卡 I：已完成（隔离后端树）**：人工审核题图可通过真实课堂 HTTP 路径安全绑定并跨会话恢复。

- 新增 `PUT /api/classroom/sessions/{session_id}/problem-source`。它只读取当前课堂属主的 `File` 记录，要求非删除、`file_type=image` 且状态为 `uploaded/parsed`；使用服务器 `File.sha256`、审核转写和语义合同构建题图来源，再重新签名课堂 `source_contract`。
- 客户端请求不含可写 hash；会话不属于当前用户、图片不属于当前用户、不是图片或未上传状态均返回结构化拒绝。此端点不调用文件解析、OCR、Mimo 或任何视觉模型。
- 失败测试先得到未定义端点的 404；实现后真实登录→创建课堂记录→创建已上传图片→绑定→重开课堂详情回读来源合同的 HTTP 回归 `1 passed`。测试环境仍打印既有知识点外键初始化告警，未导致失败。

**P4 下一卡**：补齐跨用户、非图片与未上传文件的 HTTP 拒绝回归，并把 `problem_source_sha256` 传入图形 block/课堂重试请求，使任何题图复用都必须来自同一审核合同。

## 10. 来源

- 本地核心实现与日志：`D:\math-arena\services\api\app\domains\classroom`、`D:\math-arena\services\api\app\skills\socratic_solver`、`D:\math-arena\backend.out.log`。
- 官方 OpenAI 文档：[Agents SDK](https://developers.openai.com/api/docs/guides/agents)（会话、工具、护栏、追踪与评测的编排边界）。
- 参考项目：[awesome-geogebra-ai](https://github.com/Ceiei/awesome-geogebra-ai)、[SocraticLM](https://github.com/Ljyustc/SocraticLM)、[MathTutorBench](https://github.com/eth-lre/mathtutorbench)、[agentic-rag](https://github.com/ch040602/agentic-rag)。

---

## 11. 第二轮升级执行记录（2026-08-29 晚，ZCode 接手）

本轮在主工作区（`feat/backend-m1`）直接落地，覆盖"对话答非所问/复读、动态图像、历史与入口、垂类调研复用"四条线。所有结论均有测试或真实模型运行证据。

### 11.1 对话质量（P2 深化：从"不降级"到"判得准、不复读、接得住"）

codex 前序 P2 只保证"模型给出 clarification 时不再退化为跑题"；本轮解决剩余三个真实故障源：

| 根因 | 修复 | 证据 |
| --- | --- | --- |
| judge 看不到"老师上一句"，无法识别学生在回应（截图事故主因） | `plan.recent_tutor_msgs` 环形缓冲（`_stream_student_text` 成功路径记录）；`JUDGE_USER` 注入【老师上一句】块 | `main.py:_judge/_record_tutor_msg`；测试 `test_judge_sees_tutor_last_question_and_misconception_corrects` |
| 短质疑（"难道不对吗"）依赖 LLM 判类，有误判 off_topic 风险 | `_CHALLENGE_RE` 确定性短路：≤40 字且命中质疑/求解释措辞 → 直接 clarification（sympy 快速通道仍在之前优先） | e2e 日志 `socratic.judge_challenge_rule message=难道不对吗` |
| off_topic 无差别固定话术，连续触发即复读 | 首次跑题走 LLM 个性化拉回（`OFF_TOPIC_REANCHOR_USER`，带上一问+禁令不复读）；连续跑题/生成失败/疑似 JSON/与上句查重命中 → 确定性轮换文案（`OFF_TOPIC_REANCHOR_VARIANTS` 三级递进）+ `off_topic_streak` 计数与清零 | 测试 `test_off_topic_reply_never_repeats`（三次回复两两不同） |
| 概念混淆型错误（导数/极值 vs 极限存在）缺纠正抓手 | `JUDGE_SYSTEM` 新增"学生在回应就绝不算跑题"纪律 + 混淆信号判定；`WRONG_FEEDBACK` 增加"点名混淆的两个概念对象"任务 | e2e 实测：模型回复"你把函数极值的导数条件套到了极限存在上——这两个判断的对象不同" |

**真实模型端到端验收（MiMo v2.5-pro，`services/api/_e2e_dialog_upgrade.py`）**：极限题多轮对话 3 项验收全过——误解纠正✅、质疑不进固定话术✅、三次回复不重复✅。回归：`test_socratic_solver.py` 42 passed。

**附带发现（新 bug，待开卡）**：截图中极限题正确答案为 A（a=−1），但智能出题的答案钥匙标为 D.3（把极限值 3 误当 a 的值），自带解析"解得 a=−1…故选 D"自相矛盾；本轮 e2e 中 solver 答出 A（正确）。这是题库/出题链路的判分键错误，与对话链路无关。

### 11.2 动态图像（P4 对话侧：补齐圆锥曲线 + 修复配图门控漏判）

- `figure_renderer.py` 新增 `conic` 类型：椭圆/双曲线/抛物线，等比投影不变形；F₁/F₂ 自动标注、渐近线/准线虚线、焦半径虚线（焦点三角形直接可画）；标注点支持 `t` 参数（动点）或坐标，**校验期强制点在曲线上**（不在即拒绝——图形真实性底线与课堂题图合同同思想）；渐进揭示 2 帧（曲线+焦点 → 标注点/辅助线）；`check_svg_invariants` 增加标注点/焦点缺fatal 检查。测试 `tests/test_figure_conic.py` 11 passed。
- **e2e 实测**（真实模型）：椭圆焦点三角形题 3 步成解，conic 图 F₁/F₂/M 全部出现在 SVG，不变量通过；立体几何题 3 张 polyhedron 图（构建→建系→二面角法向量），A–E 五个顶点全帧标注齐全。
- 修复 `FIGURE_TOPIC_RE` 门控漏判：补"多面体/二面角/垂直/平行/异面/法向量/棱"——e2e 曾实测"多面体 ABCE…二面角 D-AC-E"不触发配图。负例（纯计算/闲聊）仍正确排除，`test_socratic_figures.py`+conic 共 30 passed。

### 11.3 前端（P3 最小闭环）

- `DialogView.vue` 顶部"第 N 步/共 5 步"徽标从"assistant 消息数+2 封顶 5"伪造值改为消费后端 `socratic_progress`/`socratic_start`/`socratic_complete` 卡片（教学状态唯一事实源）。
- `V4Layout.vue` "可视化讲解"从硬编码 `unconfigured` 改为路由到 `/dialog`（F13 图形管线已在对话流中生效，MathFigure 支持 frames 渐进 + 动态演示按钮）。
- 历史会话核实：`ConversationSidebar`（分组/搜索/无限滚动/置顶重命名）与 `/agent/conversations` 后端接口均已存在，只显示于 /dialog 路由；用户截图未见列表，大概率是旧构建（存在多个 dist-*）或数据加载失败，**待真实浏览器登录态验证**（本轮未做，属 P6）。前端生产构建通过（3.71s）。

### 11.4 垂类调研（复用依据，全部已 clone 到 `D:\AI对话` + `_study_notes\` 10 篇笔记）

新增 10 仓库（全部 `git ls-remote` 验证后 clone，纠错 EduChat 真实仓库为 icalk-nlp/EduChat）：tutor-gpt、EduChat、ToRA、Math-Verify、manim、jsxgraph、ragflow、FastGPT、RapidOCR、MiMo-VL。连同前一轮 5 仓库共 15 个。

与本轮修复的直接对应：
- 反复读/单问题结尾：tutor-gpt `utils/prompts/response.ts:35`（"每轮只以一个相关问题结尾"硬规则）——已等价落进 `OFF_TOPIC_REANCHOR_USER` 与 guide 链既有约束。
- 学生回答分类：FastGPT `classifyQuestion` 受限枚举节点思想 ≈ 本轮 `_VERDICTS` 枚举 + `_CHALLENGE_RE` 规则层（规则优先、LLM 兜底，比纯 LLM 分类更稳）。
- 求解黑箱：ToRA 的 ```output 停止符 + 沙箱回填循环即本仓库已有 TIR 链路的同源设计（`main.py:_solve_once`）；终答案校验可接 Math-Verify `parse+verify`（pip 即用）替代自维护等价判定。
- 动态图像：jsxgraph 的"AI 出 JSON 配置 → 前端 board.create"与本项目 figure_params → 确定性 SVG 同构；其 `conic/view3d` 元素是前端可交互（拖动/旋转）的下一步升级路径；manim 适合离线讲解视频。
- Agentic RAG：ragflow `agentic_rag_graph.py`（planner→检索→充分性审查→缺口改写）+ `sufficiency_select.md` + `[ID:i]` 句级引用协议，是 P5 主对话侧接线的蓝本（见 11.5）。

### 11.5 RAG/知识库现状评估（P5 基线事实）

- 主对话链路（`app/kernel/rag.py` + `skills/qa_rag`）**不是 agentic RAG**：单轮"改写→三路召回→RRF→rerank→top-1 相关性门槛（`rag_refuse_threshold`）"，`answerable` 仅由 top-1 分数决定（rag.py:288-315），无充分性判定、无冲突检测、无句级引用映射。qa_rag 的"资料未覆盖就说明无法确认"只是提示词约束，不可机检。
- 课堂链路（untracked `rag_orchestrator.py`）已有 scope=student + textbook 白名单与题图条件阻断，为全平台最严边界；codex 在隔离树做的 `rag_evidence.py` 充分性门禁（sufficient/insufficient/conflicting/unanswerable）尚未接入主仓库任何真实回答路径。
- `D:\知识库` 原始目录约 1.36 万文件（约 1.14 万 JPG + 大量 LaTeX 宏包源码），仅 `AC切片\processed` 白名单批次被可信导入器入库——索引语料干净，但"整目录通用导入"路径一旦打开就会关键词污染，必须维持导入层默认拒绝。
- **P5 接线卡（下一轮）**：①把 ragflow 充分性 prompt 模式移植进 `RAGPipeline.retrieve` 的可选 `evidence_requirements`（隔离树已有实现可迁）；②qa_rag 生成期接 `[ID:i]` 句级引用协议（ragflow `citation_prompt.md` / FastGPT `AIChat.ts` 模板）；③精确求值/证明结论永不走 RAG（路由到解题器）。

### 11.6 后续升级安排（自动化推进卡，按优先级）

| 卡 | 内容 | 验收 |
| --- | --- | --- |
| N1（P2 收尾） | judge 真实模型金标评测：30 条匿名化对话（含质疑/混淆/跑题）离线跑分类准确率；`_CHALLENGE_RE` 词表按误报率调参 | 误判 off_topic 率 0；质疑→clarification ≥95% |
| N2（出题判分） | 修复智能出题答案钥匙错位（截图极限题 D vs A）；出题后用 Math-Verify 独立复核答案-选项映射 | 金标题答案键 100% 正确 |
| N3（P4 深化） | 对话侧 figure_params 与题图合同 hash 绑定（复用 codex `problem_input_contract`）；MiMo-VL 多模态识别原题图 → planner 注入"原题图描述" | 椭圆/立体题图形保留题图点名；无合同不称"原题图" |
| N4（P3 闭环） | 真实登录态浏览器回归：历史侧栏可见性、进度徽标、可视化入口；失败课堂可见 | 三视口无遮挡；历史恢复 100% |
| N5（P5 接线） | 11.5 的三项 RAG 接线 | 引用覆盖率 100%；证据不足不生成确定结论 |
| N6（交互升级） | 前端接 JSXGraph：figure_params → board.create 可拖动参数图；立体用 view3d 旋转 | 焦点三角形动点拖动联动；失败降级静态 SVG |

本轮未做（诚实声明）：真实登录态 UI 走查、数据库迁移执行、部署；`_CHALLENGE_RE` 与 judge 提示词的真实模型大样本评测（N1）；出题判分修复（N2）。对话"零问题"的诚实边界：判定规则层已消除已知误判路径并有回归拦截，但 LLM judge 本身仍需 N1 的金标评测持续校准。

---

## 12. 第三轮执行记录（2026-08-29 深夜，N1/N2/N4 卡 + 登录修复）

### 12.1 N2：出题判分键独立复核闸（已上线三条出题路径）

- 新增模块级 `verify_answer_key(quiz_data, llm, request_id)`（`app/skills/smart_quiz/main.py`）：不带标准答案黑盒重解一遍。choice 比对选项字母；blank 用 sympy 等价比对（文本型跳过）。复核器自身故障（调用异常/输出非法）不拦题只记 note——复核器抖动不应拒绝出题；但一旦复核不一致必须判失败（错答案键直接损害学习，宁严勿松）。
- 接线三条路径：chat 出题（`_three_gates`）、practice 组卷（`student_router`）、模拟考试（`mock_exam._gen_one`），失败均走既有的"带反馈重出 → 诚实降级"机制。
- 回归：`tests/test_smart_quiz.py` 32 passed，含截图事故直接复现用例（极限题答案键 D vs 独立复核 A → 判失败）。测试 MockLLM 升级为 scene 感知队列（复核走独立队列，不与生成互抢）。

### 12.2 N1：judge 真实模型金标评测（`_eval_judge.py`，报告 `.tmp_e2e_out/judge_eval.md`）

- 24 例六类覆盖（correct/partial/wrong+misconception/clarification/new_problem/off_topic），真实 MiMo 逐例判定。
- **总准确率 21/24 = 88%；截图事故专项全过**：「因为导数为零可以取到极值」→ wrong+concept（修复前 off_topic）；质疑组 8/8 全部 clarification（其中 5 例走 `_CHALLENGE_RE` 确定性短路，不经 LLM）；off_topic/new_problem 无误放行。
- 3 例差异均为金标宽严争议（如"给出正确通项公式"判 correct vs partial、misconception 细分类别），非跑题/复读类故障，留作金标修订输入。

### 12.3 登录注册修复（用户报告的阻断问题）

- **根因**：`identity/router.py` 的 `login_sms` 端点查不到用户即抛 `AUTH_ROLE_NOT_AVAILABLE`——service 层 `login_sms` 的"建号+绑学生身份"自动开通能力从未接线，任何未注册手机号都被"该手机号尚未申请此身份"挡住。
- **修复**：①手机号不存在 → 调 `IdentityService.login_sms` 自动开通（账号+approved 学生绑定，幂等）；②已有账号但缺学生绑定 → 幂等补绑后重试解析。仅学生身份自动开通；教师/科研身份仍走申请/审核，不在此放行。安全性依据：自动开通只发生在短信验证码核验通过之后（challenge consume 前置），凭手机号持有事实即可开户，与业界"验证码登录即注册"一致。
- 回归：`tests/test_auth.py` 20 passed，新增"全新手机号登录即注册""已有账号缺绑定幂等补绑""演示模式教师/科研自动开通（学生+专业身份同时 approved）""生产模式（审核开启）教师端仍 403 且不建账号"四类真实 HTTP 用例。

**2026-08-29 深夜补充（按用户确认的需求口径"未注册直接登录=自动注册"补齐专业身份与前端路由）**：

- `IdentityService.login_sms` 增加 `role/review_enabled` 参数：演示模式（`auth_professional_review_enabled=False`，当前默认）下，未注册手机号选教师端/科研端登录 → 直接开通该专业身份（approved）+ 学生身份，写 `role_review.bypassed` 审计日志（source=login_auto_provision）；生产模式（审核开启）下专业身份仍 403 拒绝且不建账号，必须走申请审核。
- 前端两处路由劫持修复（`stores/auth.js`）：`deriveStatus` 的 onboarding 状态与 `applyAuthResponse` 的强制 onboarding 覆盖此前不分身份——任何新账号（含自动开通的教师/科研）都会被路由守卫劫到 `/onboarding/student` 学生建档页。修复后引导只作用于学生身份；浏览器实测：新手机号选教师端 → 验证码登录 → 直接进 `/teacher/today` 教师工作台；新手机号学生端 → 仍正常进学生建档引导。前端构建通过。

---

## 13. 第四轮执行记录（2026-08-30 晚：变式链误拦 + 出题配图 + 题库建设方案）

用户实测报告四个问题：①立体几何错题求变式被"质量门阀"拦截不出题；②"题目明明说了如图结果图也没有"；③题库/母题体系空缺（D:\知识库题目无图、缺母题检索）；④引导式动态图像讲解现状存疑。

### 13.1 问题一确诊：闸拦得对，但"拦了就不出"且模型会错位——已修复

真实模型复现（`_diag_variant.py`）抓到完整失败链，**两段根因**：

1. **答案三处错位**（第二次尝试）：模型把解答题转选择题时，self_check.note 里写"已独立验算二面角余弦值为 √3/3，对应选项 A"，`answer` 字段却填 B，解析结尾写"故选 C"——三处互相矛盾。**质量闸正确拦截**（自检 flag + 独立盲解复核 + 一致性机检联动，这正是"用 AI 数学能力验证"，没有辜负设计），但重试仅 1 次且无针对性反馈 → 直接降级不出题。
2. **审题挣扎导致输出损坏**（第一次尝试）：模型把平行四边形 BCDE 的对边搞错（臆造"AE∥CD"推出 AE⊥AE 矛盾），陷入"修正/假设错误"的自我怀疑循环，解析里漏出命题过程语言，输出超长被 4000 token 截断 → JSON 坏。

**修复（全部落地，回归 74 passed + 真实模型复验通过）**：

| 修复 | 内容 |
| --- | --- |
| 答案对齐自愈器 `align_choice_answer()` | 闸因"答案不一致/无法归一"拦截时不再盲目重出：收集三个独立信号——盲解复核的选项字母、盲解求值文本按归一化匹配的选项、解析"故选 X"结论——多数派一致时**重写 answer 与解析结尾**再重过闸；信号矛盾则带针对性反馈重出。抽公共函数 `blind_solve_choice()` 供复核与对齐共用 |
| 重试 2→3 次 | 出题主路径与变式链均 +1 次（几何/计算题答案错位率实测偏高） |
| 审题纪律注入变式 prompt | OCR 容错（一次性订正识别噪声，禁止在解析里输出审题挣扎）、图形关系逐条明确（平行四边形对边先列再推理，严禁臆造平行垂直）、变式条件自洽自查 |
| token 预算 4000→6000 | 变式生成（几何题审题+完整解析+自检在 4000 处实测截断致 JSON 坏） |
| "如图"闸反馈改教练式 | 从"系统不支持题目配图"改为"删掉'如图'，用文字完整描述图形（顶点名/边长/方程/位置关系），配图由系统依据描述自动生成" |

**复验结果**：同一道立体几何错题，变式链成功产出选择题变式（题干文字自包含、答案自洽、命中图形门控）。

### 13.2 问题二：出题/变式配图（已落地，前端零改动）

- 讲题链路（socratic）配图此前已工作（椭圆 conic 图、立体 polyhedron 图、函数图，e2e 验证标注齐全）。
- **本轮补齐出题/变式链路**：新增 `_quiz_figure_events()`——题目过闸后、发题卡前，复用 socratic figure planner（复用其 prompt/解析器/确定性渲染器，含 conic 支持）生成图形，以标准 `figure` 事件发出；前端 MessageBubble 的 figures 区渲染在题卡上方（**零前端改动**）。只取构图帧（frame_limit=1，不给答案性标注），planner 两轮重试，失败静默不阻断出题。
- 设计闭环：闸继续拒绝"如图"指代 → 模型改用文字完整描述几何体 → planner 依据文字描述构建 figure_params → 确定性渲染 → 学生看到真图。描述越完整图越准，形成正向约束。

### 13.3 问题三：题库/母题体系建设（P-Q1 已完成，调研已完成）

**调研结论（18 个候选仓库/数据集验证 clone 至 `D:\AI对话\_math_question_banks\`，19 篇笔记在 `_notes\`）**：

| 数据源 | 规模 | 图形 | 许可证 | 定位 |
| --- | --- | --- | --- | --- |
| GAOKAO-Bench + Updates（本地已有） | 936 题中文真题带官方详解（选择510/填空164/解答227 去重后 901） | 无图但文字自洽（带图题构建时已剔除） | Apache 2.0 | **骨架，已导入** |
| CMM-Math（ecnu-icalk/educhat-math，已 clone 644MB） | 中文 28,069 题、高中 8,521、自带 JPG 真图（高中含图 1,972）、94.7% 带解析 | A 级真图 | 未声明（商用前需确认） | 题量+图形主力（P-Q2） |
| GAOKAO-MM | 2010-2023 带图选择题 80 + 142 张真题 PNG | A 级真图直挂 | Apache 2.0 | 随 P-Q2 导入 |
| NuminaMath cn_k12 | 276,591 题（**英文翻译版**，官方流程含 translation） | 无图 | Apache 2.0 | 变式生成/教师语料，不直接展示 |
| M3Exam / deekur/gaokaomath | 782 份 2000-2026 真卷 PDF（CC BY 4.0） | PDF 原图 | CC BY 4.0 | C 级兜底补图 |

纠偏：cn_k12 不是 85 万中文题（CoT 全集 86 万中 cn_k12=27.7 万，且为英文版）；CMATH 官方仓库为 XiaoMi/cmath；M3KE test 分割答案为空不推荐。

**P-Q1 已落地**：`scripts/import_gaokao_bench.py`（dry-run 验证 + 幂等导入，hash 去重唯一约束）——**901 道真题已入库** `question_bank`（choice 510 / blank 164 / solution 227，891 带解析，source/year/真题标记/批次溯源齐全）。知识点打标（kp_source=pending）留批量卡。

**母题检索已接线**：`_retrieve_question_bank_prototype()` 题库优先预检（知识点词 ILIKE 命中真题即用，随机抽样打散）→ 未命中回落 chunks RAG。实测"数列"命中 2012 新课标真题、"椭圆"命中 2021 真题。此前出题原型检索只查 chunks（题目不在 chunks），题库等于虚设——现已修正。

**P-Q2（下一卡）**：CMM-Math 高中 8,521 题（含 1,972 带图）清洗导入（删 null 解析、`<ImageHere>` 处理、level 过滤、JPG 挂 image 字段）；GAOKAO-MM 真图随批。**P-Q3**：图形补齐三级路径（A 真图直挂 → B 程序化 figure_params：函数表达式/圆锥曲线方程/立体几何顶点表模板 → C 标 needs_figure 用真题 PDF 兜底）。

**验收门禁**：每批次抽样 100 题答案正确率 ≥97% 才放行展示；许可证不干净（CMM-Math/M3KE 未声明、CMMLU/CC BY-NC-SA）的批次商用前需确认。

### 13.4 问题四：引导式动态图像讲解现状评估

- **已工作**：讲题链路按步骤配图（构图帧→全帧渐进揭示）、椭圆/双曲线/抛物线 conic 图（含焦点三角形）、立体几何 polyhedron（顶点标注、多视角）、函数图（自适应采样）；前端 MathFigure 渐进帧播放 + "动态演示"按钮（GeoGebra 构图）；不变量检查拦截坏图。
- **本轮新增**：出题/变式卡片配图（见 13.2）。
- **剩余缺口（开卡）**：①前端接 JSXGraph 做可拖动参数交互图（N6）；②MiMo-VL 多模态识别原题图 → 讲题/配图链路注入"原题图描述"（N3）；③双师课堂 GeoGebra 图与对话 figure 管线的合同打通。

### 13.5 本轮改动文件

- `app/skills/smart_quiz/main.py`：`align_choice_answer()`/`blind_solve_choice()`/`_match_option_by_value()`、两条生成路径接线对齐自愈、重试 2→3、变式 token 6000、`_quiz_figure_events()` 配图、prompt 审题纪律/三处一致/配图纪律、"如图"闸反馈改教练式。
- 诊断脚本（本地不入库）：`_diag_variant.py`、`_diag_parse.py`。
- 回归：smart_quiz 32 + socratic 42 = 74 passed；真实模型复验变式链成功出题。

### 13.6 第五轮执行记录（2026-08-30 深夜：图形画错/动态演示 500/思考模式三连修）

用户实测报告：①讲题配图把多面体 ABCE 画成了无关的四棱锥且无顶点字母；②"动态演示"按钮 HTTP 500；③求解耗时长且打开思考模式看不到思考过程。

| 问题 | 根因 | 修复 |
| --- | --- | --- |
| 图形画错且无字母 | (a) 图形规划器只看 OCR 文本，**原题图从未进入配图链路**（多模态 MiMo 不在链路里，用户直觉正确）；(b) 规划器面对非标准多面体套了四棱锥模板；(c) 引导阶段只发"轮廓帧"（show_labels=False），学生看到的图没有任何字母 | ①图片 file_id 从路由层透传 socratic（`image_file_ids`）；新增 `_describe_original_figure()`：多模态 MiMo（mimo-v2.5，OpenAI content parts 透传已验证）直读原题图 → 顶点位置/虚实线结构化描述 → 注入规划器 prompt；实测用户原题图读出"ABCE 五顶点相对位置 + AD/EB 虚线"完全正确。②planner 纪律：非标准多面体必须 polyhedron 显式顶点表，禁套锥体模板。③立体图改单帧全标注（顶点字母是题干已知信息不泄题，防泄题靠规划器要素纪律保证） |
| 动态演示 500 | `POST /api/figures/ggb` 无兜底 try/except，未处理异常以 500 逃逸（前端契约是 50400 降级静态图）；且前端只发 caption 一句话，生成器靠猜 | 端点整体 try/except → 50400 降级；前端把确定性渲染用的 figure_params（顶点/边/面）随请求下发给生成器，构造精度大幅提升 |
| 思考模式看不到过程 | 前端 thinking 面板与事件契约现成（messageModel case 'thinking'），但 socratic `_solve_verified` 无条件吞掉 `_thinking` 事件——开关形同虚设 | thinking=True 时思考流实时以 `thinking` 事件下发（快速模式仍不外发）；耗时本身是深度推理固有成本，状态条已有分段提示 |

- 验证：`derive_figure_frames` 四棱锥单帧含 P/A/B/C/D 全部标注；MiMo 视觉直调用用户原题图实测通过；回归 97 passed；前端构建通过。
- 涉及文件：`agent_router.py`（image_file_ids 透传）、`socratic_solver/main.py`（视觉读图+思考流）、`figure_renderer.py`（单帧标注）、`prompts.py`（多面体纪律）、`figures_router.py`（500 兜底）、`MathFigure.vue`（figure_params 下发）。

### 12.4 N4：真实登录态浏览器回归（Chrome 1920×1080，前端 dev + 后端 :8000 + 真实 MiMo）

| 检查项 | 结果 |
| --- | --- |
| 任意手机号模拟登录 → 引导建档 → 进入工作台 | ✅（依赖 12.3 修复） |
| 对话学习页历史侧栏 | ✅ 存在（新对话按钮/搜索/分组/置顶）；用户截图缺失为旧构建 |
| 极限题全流程（发送→题库检索→求解→苏格拉底开场） | ✅ 徽标"第 1 步 / 共 6 步"（读后端状态卡） |
| 学生答"分母趋于 0" | ✅ 先具体肯定再追问分子条件，KaTeX 正常 |
| 学生答"因为导数为零可以取到极值" | ✅ 无"放一放"回退，对比"极限存在性 vs 极值"纠错 |
| 学生质疑"难道不对吗" | ✅ 澄清分支：举例讲 3/0→∞ 与 0/0 型区别 + 可核对问题 |
| 刷新页面会话恢复 | ✅ 消息/徽标/自动标题全部还原 |
| 新发现 bug：发消息后侧栏不实时刷新 | ✅ 已修（`onConversationId` 补 `conv.load()`），新会话即时入列，无需手动刷新 |

- 前端生产构建通过（3.25s）；后端联合回归 121 passed（auth+smart_quiz+socratic+conic+figures）。

### 12.5 本轮改动文件

- 后端：`app/domains/identity/router.py`（登录自动开通）、`app/skills/smart_quiz/main.py`（闸 5 复核）、`app/gateway/student_router.py`（practice 路径接线，与用户未提交改动同文件，仅暂存本卡 hunk）、`app/skills/mock_exam.py`（组卷路径接线）、`tests/test_auth.py`、`tests/test_smart_quiz.py`。
- 前端：`src/pages/student/DialogView.vue`（侧栏实时刷新；叠加第二轮的步数徽标修复）。
- 评测脚本（按 `_` 前缀约定留在本地不入库）：`_eval_judge.py`、`_e2e_dialog_upgrade.py`。

### 12.6 剩余执行卡（不变，见 §11.6）

N3（题图合同 hash 绑定 + MiMo-VL 原题图识别接入 planner）、N5（RAG 充分性门禁 + 句级引用接线）、N6（JSXGraph 可交互图）。另新开 N7：UI 排版打磨（1920px 下消息区垂直空间利用率、题卡与输入区视觉层级——N4 截图可见消息少时中部留白偏大）。
