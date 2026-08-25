# 学生端双师课堂 · 合并联调报告与提交说明（2026-08-25 终版）

## 一、本次提交范围（OpenMAIC 融合改造，学生端）

### 后端（worktree services/api）
| 文件 | 内容 |
|---|---|
| `app/models/classroom.py` + 迁移 `m2_020_classroom_sessions.py` | AI 数学课堂会话（OpenMAIC 语义：topic 即可生成，course_id 可选，含 updated_at） |
| 迁移 `m2_019_submission_attachments.py` | 作业附件 attachments 多图列（配套 coursework.py） |
| `app/domains/classroom/stage_router.py`（新） | 两段式生成：数学专属大纲（8~15 页）+ 逐页内容（text/latex/example/note）；kp 白名单；LLM 失败确定性兜底；**JSONB 变更检测修复**（list(slides)） |
| `app/domains/classroom/course_router.py` | 课程预处理后台任务改 `asyncio.create_task`（修复本环境不执行问题） |
| `app/domains/files/router.py` | 拍照题 mimo_rewrite（RapidOCR→mimo 规整 LaTeX）；低置信标记不静默使用 |
| `app/domains/teacher/grading.py`、`app/gateway/student_router.py`、`main.py`、`models/__init__.py` | attachments 透传 / 会议室挂载 / 注册 |
| `deliverables/student-refactor/` | 验收清单 + 迁移映射 + 本报告 |

### 前端（D:\frontend，学生端）
| 文件 | 内容 |
|---|---|
| `pages/student/DualView.vue` | OpenMAIC 语义播放器：主题直接生成 / 课程增强 / 后台轮询 / 大纲侧栏 / TTS 语速 / 例题翻转 / 每页自查 / 白板 / 键盘翻页 / 刷新回显（含空内容兜底） |
| `components/student/WhiteboardCanvas.vue` | 白板（画笔4色/激光/橡皮/清空）+ **公式板书**（wb_draw_latex：LaTeX 贴板可拖可删） |
| `components/student/HomeworkPhotos.vue` | 图片作业多图上传/预览/OCR |
| `components/student/FlashcardReview.vue` | OpenTutor 式 3D 翻牌闪卡（FSRS 四档 + 键盘快捷键） |
| `pages/student/ErrorsView.vue` / `GraphView.vue` / `OverviewView.vue` / `AssignmentView.vue` | 拍错题入本 + 闪卡入口 / 星系视图真实化 / 课堂任务速览 / 多图组件接入 |

## 二、联调验证矩阵（本轮实测，隔离测试库 math_arena_wt）
| # | 链路 | 结果 |
|---|---|---|
| 1 | alembic 全量迁移 head=m2_020（干净库重建后通过） | ✅ |
| 2 | 学生端 14 接口（auth/错题/图谱/学情/作业/课程/课堂/掌握度/实验室） | ✅ 全部 200 |
| 3 | OpenMAIC 语义：仅 topic 生成（"三角函数图像与性质"） | ✅ ready，8 页落库 |
| 4 | 课程增强生成（course_id，review 模式） | ✅ ready，8 页落库 |
| 5 | 教师登记→预处理后台自动 ready | ✅（asyncio.create_task 修复验证） |
| 6 | 班级共享课程学生可见 | ✅（courses total=3，ready 可见） |
| 7 | 错题 入本→复习→学情 | ✅ |
| 8 | 前端 vite build | ✅（含白板公式/闪卡/多图组件） |
| 9 | 浏览器登录态全页面冒烟（登录→5 页→生成） | ✅ PASS（含 LaTeX sinα=y/r 渲染） |
| 10 | 空白页缺陷（残缺会话回显） | ✅ 已修复（过滤+兜底+清理） |

## 三、部署/上线步骤
1. **新迁移执行**：`alembic upgrade head`（m2_019 → m2_020）
2. **注意迁移合链**：本项目开发库（math_arena）当前跑 `om2_openmaic_*` 链（D:\math-arena 主项目并行），与工作树 `m2_*/m3_*` 链为两套体系——**合库前需先协商迁移合并策略**，本次迁移仅在隔离测试库验证。
3. **环境变量**：本地联调时系统环境变量 `DATABASE_URL` 会覆盖 .env（指向旧 5432），须显式覆盖到 54329。
4. **前端代理**：`VITE_API_PROXY_TARGET=http://<后端地址>`（默认 8000 不变）。

## 四、已知限制（如实说明）
- 演示短信仅白名单号（13800000000 / 13900001001）可用
- 星辰流预处理缺 `AGENT_USER_INPUT` 参数（既有配置）→ 自动降级本地 mimo
- 本地文件存储的预签名图在过期后失效（既有）
- 未登录路由守卫竞态为既有问题（未在本次改动范围）
- 拍照识别为 RapidOCR + mimo 文本规整（mimo 端点确认不支持图像输入；探测返回 404「No endpoints found that support image input」）

## 五、服务状态（联调后正在运行）
- 后端 uvicorn `127.0.0.1:8010`（连 math_arena_wt）｜前端 vite `http://localhost:5177`（proxy→8010）
- 登录体验：手机号 13800000000 / 13900001001 ＋ 点"获取验证码"（页面显示演示码）
## 六、第二轮补齐验收（2026-08-25 晚）
- 页内 AI 课堂助手（DualView）：随讲随问改页内即时多轮问答（useChat+MessageBubble 复用，不再跳转）；「🎯 随堂小测」「🤔 没听懂这里」「📌 本课小结」一键直达（smart_quiz/socratic 技能）。
- 翻页动效对齐 OpenMAIC ease-out-quart（cubic-bezier(0.22,1,0.36,1) 280ms translateX）。
- 拍照识题全链路：修复 local: 存储下 parse 被"即时人工复核"短路的缺陷；实测 OCR 乱码 → mimo-v2.5-pro 文本通道规整为 LaTeX（engine=mimo_rewrite，低置信 0.0 标记供复核）。
- 迁移合链方案已输出（migration-merge-plan-2026-08-25.md）：两链共享 auth_001/m2/m3 主干，dev head=m3_003，推荐以 om3_001/om3_002 挂 dev head 完成合链。
- 浏览器端到端终验 PASS：回显播放器 / 生成新课堂 / AI 助手流式回复（Markdown+LaTeX）/ 随堂小测（结构化选择题+解析+错题收录）/ 翻页动效。

### 已知注意（新增）
- 随堂小测首次触发偶发一次 POST /api/agent/chat 瞬时中止（重试即成功）——并发启动新流时中止逻辑，建议跟踪。
- 「教材知识库」检索零命中不影响生成，属召回优化项。
- 拍照 OCR 文本长度 < 20 字符时不触发 mimo 规整（_RAPIDOCR_MIN_TEXT_LEN 设计阈值，低置信不静默使用）。