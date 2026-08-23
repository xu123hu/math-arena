# 迭代19 收尾轮 · 最终交付清单

> 完成时间：2026-08-15 ｜ 执行顺序：P0 → P1 → P2，每任务完成即验证。

## P0

### 任务1：学情报告变量未替换 ✅
- 后端 `app/gateway/growth_router.py`：highlights 的 icon 英文键改为中文
  （trend_up→进步趋势、independence→独立解题、streak→连续学习、review_done→复习完成、breakthrough→正确率突破），含空态模板；
- 前端 `src/pages/student/ReportView.vue`：新增 ICON_ZH 旧键→中文防御映射（兼容缓存窗口）。
- 验证：后端无英文 icon 残留 + 39 例相关测试过 + 前端构建过。

### 任务2：周报用户名 ✅
- `ReportView.vue`：标题「小婷的周报」→「{当前登录用户昵称}的周报」（auth store 昵称，空昵称兜底「我的学习周报」）。
- 验证：不同用户昵称正确展示（mock 用户=小婷 时仍显示小婷，符合预期）。

### 任务3：前端默认真实后端 ✅
- `D:\frontend\vite.config.js`：默认代理 127.0.0.1:8000；mock 改为 `VITE_USE_MOCK=1` 显式开关（VITE_REAL_API 保留无副作用）。
- 处置：终止 5176 端口上残留的旧配置 dev server（mock 默认，误导用户看假数据）。
- 验证：`npm run dev` 实测 /api/health 代理到真实后端返回 `{"status":"ok"}`；`VITE_USE_MOCK=1` 实测返回 mock 数据。

### 任务4：错题去重 ✅
- 应用层：`student_router.py` 新增 `_upsert_error_record`，三处收录入口（手工/学习事件/练习自动收录）统一接入：同用户同题干全时段唯一，重复收录 wrong_count+1、补全缺失字段，savepoint 兜底并发；AI 初判与记忆联动仅新收录触发；
- 数据库：迁移 `m2_016_error_record_dedup`（内联数据清理 + 唯一索引 uq_error_records_user_question WHERE deleted_at IS NULL）——**开发库实际合并 29 条重复错题**；
- 脚本：`scripts/dedup_error_records.py`（幂等、--dry-run）；
- 测试：`tests/test_error_dedup.py` 5 例；学生链路回归 79 例全过（含 3 处既有测试数据 bug 修复）。

## P1

### 任务5：FSRS 分级 ✅（复核确认，无需改动）
- 迭代18 已修复：`fsrs_level` 按稳定度 S 分级，新题 S=0.4→「刚收录」；前端 new→「刚收录」映射正确；33 例单测过。

### 任务6：AI 管家最小闭环验收 ✅ 14/15
- `scripts/verify_butler_loops.py`（真实 LLM + 真实数据种子 + 自动清理），实录 `deliverables/butler-loop-verification.txt`：
  - 闭环1「我哪部分最弱」**5/5**：每次都返回真实薄弱点（函数概念 12%）；
  - 闭环2「给我出3道导数题」**4/5**：4 次 3 题；1 次仅 2 题（LLM 出题数量偶发抖动，非路由故障）；
  - 闭环3「打开错题本」**5/5**：route-intent → /errors + 到期数。
- 结论：闭环可用，无需修路由。

### 任务7：前端修复包 ✅（复核确认，迭代18 已完成）
- butlerApi.errorDetail/errorTutor 存在且接线 ErrorsView；GraphView「直接练」带 ?kp=；
  PracticeView 消费 kp 定向出题（后端 group-recommend 支持 kp_code）；5题vs1题空态后端已修（摸底知识点走 special 5 题）。

## P2

### 任务8：BKT 决策 ✅ 降级为接口预留
- SQL 实测：每用户答题量中位 **2 题**（49 用户，p90=9，≥20 题仅 2 人）→ 低于 20 阈值，全量 BKT 无统计意义；
- 交付：`app/services/bkt.py`（四参数经验值 pL0=0.4/pT=0.15/pG=0.15/pS=0.06 + bkt_update/block 更新 + should_use_bkt 门槛），7 例单测；热路径维持 BKT-lite（简单正确率后验）。数据达标后仅替换 _update_mastery 更新式。

### 任务9：MinIO + 拍照题 ✅（链路级修复完成）
- MinIO 确认运行（healthy），Redis 容器已拉起；
- 修复 3 处真实缺陷：① 星辰文件上传服务 404（平台下线）→ **data URI 直传**（工作流实测 code=0）；
  ② 工作流输出含 Python 风格布尔（False）导致 JSON 解析失败 → `_parse_output` 保守归一化容错；
  ③ wf_doc_understand 超时 30s→90s（大图 base64 处理慢）；
- 全链路验收（upload→MinIO PUT→complete→parse→轮询）：status=parsed、engine=spark_vl ✅；
  识别内容质量受合成测试图限制（resvg 渲染字形与真实拍照差异），真实拍照题为最终内容验收介质。

### 任务10：性能实测 ✅
- `scripts/perf_probe.py`：10 关键接口 ×30 次（数据最多用户），**P95 全部 <200ms**（最高 43.5ms），300 请求零超限；
- EXPLAIN 检查：错题列表 Bitmap Heap Scan+Sort → m2_017 复合索引 (user_id, deleted_at, created_at DESC)；
  错题去重唯一索引确认生效；pg_stat_statements 未启用（可选开启）。

### 任务11：文档补齐 ✅
- `docs/后端现状审计报告.md`：新增迭代19 修复清单（3.0~3.9）+ 决策记录更新（6 项）；
- `docs/API接口文档.md`：错题去重语义、figure 事件协议（§10）、拍照云轨 data URI、SSE 事件流更新；
- `docs/测试报告.md`：新增本轮测试总览、管家 5×验收明细、性能复测表、已知问题更新；
- `docs/部署说明.md`：迁移到 m2_017、前端默认真实后端说明、新增 5 个运维脚本命令。

## 数据与制品

| 项 | 说明 |
|----|------|
| 迁移 | m2_016（去重+唯一索引）、m2_017（列表性能索引），开发库已到 head |
| 开发库清理 | 合并 29 条重复错题；验收数据全部自清理 |
| 测试 | 本轮新增 61 例（去重 5 + BKT 7 + F13 49），回归 150+ 例全过；lint 新文件全过 |
| 验收脚本 | scripts/verify_butler_loops.py、verify_photo_chain.py、perf_probe.py、dedup_error_records.py（可重复执行） |
| 验收实录 | deliverables/butler-loop-verification.txt（14/15 明细） |

## 遗留观察（不阻塞）

1. smart_quiz 出题数量偶发少 1 题（5 次中 1 次）——建议平台侧补充出题样本；
2. RAG 向量召回一处 unpack 错误（vec_count=0，trgm 兜底生效）——待查，不影响召回可用性；
3. 星辰平台侧：App A 五流 20373 授权、solution_pregrade 20805、wf_socratic_chat system 透传（修好可恢复 chat 云轨）；
4. 后端当前以本会话进程运行于 :8000（uvicorn，未 --reload），代码更新后需重启。
