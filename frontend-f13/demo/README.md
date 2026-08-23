# F13 demo —— MathFigure 组件独立演示/验证

> 用途：不依赖 `D:\frontend` 的独立验证环境（本会话工作区无浏览器可运行、
> 前端目录只读，故以「SFC 编译 + SSR 冒烟 + 静态预览」方式完成组件验证）。
> 交付给 `D:\frontend` 的正式文件见上级 `README.md`。

## 结构

```
demo/
├── src/                       # 演示源码（MathFigure.vue 与前端交付包同一份）
│   ├── App.vue                 # 对话气泡模拟：流式状态 + 3 张图（真实后端渲染数据）
│   ├── main.js
│   ├── demo.css                # tokens 子集（对齐前端 tokens.css）
│   ├── figureData.js           # 由 scripts/render_f13_samples.py 生成（真实渲染 data_uri）
│   └── components/{chat,common}/  # MathFigure.vue / UiIcon.vue
├── build.mjs                   # @vue/compiler-sfc 零 spawn 编译 SFC -> dist/*.js（沙箱禁 vite）
├── server.mjs                  # 极简静态服务器 :5210（进程内，零 spawn）
├── ssr-check.mjs               # vue/server-renderer 冒烟：断言组件渲染出图形卡 DOM
└── node_modules                # junction -> D:\frontend\node_modules（只读复用 vue 依赖）
```

## 验证步骤（本会话已执行）

```powershell
# 1. 生成真实渲染数据（后端确定性渲染 3 道典型题）
cd D:\math-arena\services\api
.venv\Scripts\python.exe -m scripts.render_f13_samples

# 2. 编译 SFC + SSR 冒烟（10 项断言全 PASS）
cd D:\math-arena\frontend-f13\demo
node build.mjs
node ssr-check.mjs

# 3. （可选）本地浏览器打开静态服务查看交互
node server.mjs
# 浏览器访问 http://127.0.0.1:5210 —— 流结束后图形帧自动播放，可点帧圆点/重播
```

> 注：本会话沙箱禁止命名管道（Chromium mojo/playwright daemon 均无法启动），
> 故浏览器截图不可用；已改用 resvg-js 将全部帧 SVG 渲染为 PNG 效果图，
> 并以 SSR DOM 断言验证组件渲染正确性（见 deliverables/f13-visual-guidance/04-verification.md）。
