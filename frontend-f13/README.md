# F13 前端交付包（安装说明）

> 说明：会话工作区 `D:\math-arena` 与前端实际目录 `D:\frontend` 分离，本目录存放
> F13 全部前端改动，按下面步骤拷贝/应用到 `D:\frontend` 即可生效。
> 全部改动零新依赖（复用现有 Vue3 + CSS 变量）。

## 文件清单

| 文件 | 操作 | 目标位置 |
|---|---|---|
| `src/components/chat/MathFigure.vue` | **新增**，原样拷贝 | `D:\frontend\src\components\chat\MathFigure.vue` |
| `patches/messageModel.js` | **完整替换** | `D:\frontend\src\components\chat\messageModel.js` |
| `patches/frontend-patches.md` | 按补丁手工应用 2 个文件 | `MessageBubble.vue`（2 处）、`mock/server.js`（3 处） |

## 安装步骤

```powershell
# 1. 新组件
Copy-Item D:\math-arena\frontend-f13\src\components\chat\MathFigure.vue D:\frontend\src\components\chat\MathFigure.vue

# 2. messageModel.js（完整替换版，已包含 F13 改动）
Copy-Item D:\math-arena\frontend-f13\patches\messageModel.js D:\frontend\src\components\chat\messageModel.js -Force

# 3. 按 patches\frontend-patches.md 手工应用 MessageBubble.vue 与 mock\server.js
```

## 改动内容摘要（供评审）

1. **`MathFigure.vue`（新增）**：figure 事件渲染组件——
   - 契约 `{step_no?, caption?, frames:[{data_uri, label}], figure_params?}`；
   - 帧渐进揭示：流式结束自动播放（1.6s/帧），帧圆点手动跳转 + 重播（对标 manim-slides 可逆步骤）；
   - 单帧退化为静态图；加载失败兜底 + 调试参数面板，绝不白屏；
   - 帧切换 `<Transition>` 淡入（reveal.js fragments 式渐进揭示），零依赖。
2. **`messageModel.js`**：assistant 消息新增 `figures: []`；
   `applySseEvent` 新增 `figure` 事件分支（push）；`fromHistory` 从 envelope
   `figure` block 还原。未知事件忽略铁律不变 → 旧后端/旧前端双向兼容。
3. **`MessageBubble.vue`**：正文之后渲染 `MathFigure` 列表（图形紧跟对应讲解步骤文本）。
4. **`mock/server.js`**：默认 socratic 回复下发 2 帧抛物线 figure 事件 + 历史持久化，
   纯前端 mock 模式即可演示/截图验证。

## 验证方式

- mock 模式：`cd D:\frontend; npm run dev`，发任意消息（默认 socratic 回复）
  → 气泡内出现「步骤 1 · 先观察这条抛物线的形状…」图形卡，流结束后自动从
  「坐标系与曲线」过渡到「标注关键点」，可点帧圆点/重播；
- 真实后端：`services/api` 运行后 `$env:VITE_REAL_API=1; npm run dev`，
  socratic 讲函数题/几何题时 figure 事件随引导步骤出现；
- 本仓库 `demo/` 提供不依赖前端目录的独立演示（见 demo/README.md）。
