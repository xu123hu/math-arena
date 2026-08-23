# F13 前端交付包 · 应用记录（2026-08-15）

## 应用结果：4 个文件全部成功应用到 D:\frontend，构建通过

| # | 文件 | 操作 | 结果 |
|---|---|---|---|
| 1 | `D:\frontend\src\components\chat\MathFigure.vue` | **新增**（F13 图形卡组件） | ✅ 写入成功 |
| 2 | `D:\frontend\src\components\chat\messageModel.js` | **增量合并**（4 处编辑，未整体覆盖） | ✅ 5 次编辑成功 |
| 3 | `D:\frontend\src\components\chat\MessageBubble.vue` | **补丁**（2 处：import + 渲染循环） | ✅ 2 次编辑成功 |
| 4 | `D:\frontend\src\mock\server.js` | **补丁**（4 处：助手函数/流式下发/done 时序/历史持久化） | ✅ 5 次编辑成功 |

## 冲突与处理

- **发现 1 处漂移**：`messageModel.js` 的 `convGroupKey()` 在我早前读取快照之后被改为
  无效日期返回 `'earlier'`（我准备的"完整替换版"仍是旧值 `''`）。
  **处理**：放弃整体覆盖，改为对当前文件做 4 处精确增量编辑，既应用 F13 功能，
  又完整保留该既有修复（已验证 `return 'earlier'` 三处仍在）。
- 其余 3 个文件的补丁锚点全部命中，零冲突。

## 各文件改动明细

### 1. MathFigure.vue（新增，284 行）
figure 事件图形卡：帧渐进揭示（流结束自动播放 1.6s/帧）、帧圆点跳转、重播、
单帧退化静态图、加载失败兜底 + 参数调试面板；零新依赖。

### 2. messageModel.js（+14 行，4 处）
- 契约注释：事件序列加入 `figure`；
- `newAssistantMsg()`：新增 `figures: []` 字段；
- `applySseEvent()`：新增 `case 'figure'` → push 到 `figures[]`；
- `fromHistory()`：新增 `figures: []` + envelope `figure` block 还原。

### 3. MessageBubble.vue（+9 行，2 处）
- import MathFigure；
- 正文/GraphBlock 之后渲染 `MathFigure` 列表（`streaming` 透传）。

### 4. mock/server.js（+52 行，4 处）
- 新增 `svgDataUri()` / `parabolaFrames()` 助手（2 帧抛物线 mock）；
- `streamReply()`：lead token 后按序下发 `figure` 事件，done 延迟重算（保证 figure 在 done 前）；
- 默认 socratic 回复挂 `figures`（mock 模式即可演示）；
- 历史持久化 envelope blocks 追加 figure 块。

## 验证

- `node --check` server.js / messageModel.js：✅ 语法通过；
- `npm run build`（vite build）：✅ 1.54s 成功；
- 产物确认：`math-figure` 组件代码已进入 DialogView chunk，
  `case"figure"`/`figures.push` 事件归约已进入 index bundle。

## 手动演示（可选）

```powershell
cd D:\frontend
npm run dev        # mock 模式：发任意消息 → 气泡内出现「步骤 1」抛物线图形卡，
                   # 流结束后自动从「坐标系与曲线」过渡到「标注关键点」
```
