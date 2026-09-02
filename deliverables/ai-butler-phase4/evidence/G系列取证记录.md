# G 系列（任务中心基建）运行时取证记录 · 阶段 3

> 日期：2026-09-02 ｜ 环境：API 127.0.0.1:8000（run_server.py）+ 开发库 math_arena（om7 迁移已应用）
> 方法：demo 短信登录两名用户，全部走真实 HTTP + SQL 取证；原始输出见同目录 01~13 号文件。

## 结果总览（验收用例表 G-1..G-9 功能轨）

| 用例 | 结论 | 关键证据 |
|---|---|---|
| G-1 幂等下单 | ✅ | 同幂等键 `evi-g1-001` 两次 POST → 同一 task `1b0509f2`，created true→false（04） |
| G-2 关页面不中断 | ✅ | 任务服务端执行到 succeeded（306ms 题库路径；LLM 路径见 G-3 的 147s），全程无页面连接（04/05） |
| G-3 进程重启自愈 | ✅ | 运行中杀进程（遗留 `running attempt=1`）→ 重启后 ~2min stale 扫描自动重拉 `attempt=2` → **147s 真实 LLM 生成 5 道椭圆题 succeeded**，通知到达（10/11） |
| G-4 失败可见可重试 | ✅ | 非法 kp → 秒级 failed「知识点不存在: MATH-NOT-EXIST」；retry → queued → failed attempt=2 错误保持可读（07） |
| G-5 运行中取消 | ✅ | LLM 补题 35% 时 cancel → cancelled，runner 不覆盖（09） |
| G-6 用户隔离 | ✅ | 用户 B 访问 A 的任务 → `code 40400`（不暴露存在性）（07） |
| G-7 since 增量 | ✅ | `?since=5分钟前` 只返回增量任务（07） |
| G-8 并发闸 | ✅ | 同用户并发 5 单 → **2 running + 3 queued**（每用户信号量=2 生效），全部可取消（12） |
| G-9 通知与降噪 | ✅ | 终态产生 `task.succeeded|练习生成已完成|jump:/practice`；dedup_key 唯一约束 + 预查双保险（06/11） |

## S-B2 黄金路径（后端段）附加证据

- 产物落库：task.result.quiz_id 对应 quizzes 行 + 5 个 quiz_items（13 号文件抽查第一题为规范 LaTeX 椭圆题，difficulty=easy，ai_generated=true）。
- 内核复用：handler 直接调用 `student_router._generate_special_quiz`（题库优先→AI 补缺→质量闸），与练题中心同一实现，无第二套生成逻辑（代码路径 `app/services/task_handlers.py`）。
- 真实 LLM 路径：零库存 kp「椭圆轨迹」全 AI 生成 5 题，自愈后续跑 147s 完成——AI 补题链路与质量闸在后台任务内同样生效。

## 已知边界（如实记录）

1. 进程中断时若 handler 事务已部分提交（progress 提交点），可能遗留孤立 quiz 行——用户可见产物以 task.result 指向的最终 quiz 为准，孤立行不进入练习记录（无用户面影响）；彻底的产物级幂等属二期（需要 handler 两阶段提交）。
2. G-10/G-11（体验轨）待前端代理交付后走查补录。
