# 前端补丁说明（F13 可视化讲解）

> 适用基线：`D:\frontend` 当前版本。`messageModel.js` 为完整替换版（见同目录），
> 下面两个文件按补丁手工应用（每个补丁给出精确原文定位）。

## 补丁 1：`src/components/chat/MessageBubble.vue`（2 处）

### 1-a 引入组件

找到（script 区 import 段）：

```js
import GraphBlock from './GraphBlock.vue'
```

在其后新增一行：

```js
import MathFigure from './MathFigure.vue'
```

### 1-b 渲染图形卡

找到：

```html
        <!-- F11 graph block -->
        <GraphBlock v-if="msg.graph" :graph="msg.graph" />
```

替换为：

```html
        <!-- F11 graph block -->
        <GraphBlock v-if="msg.graph" :graph="msg.graph" />

        <!-- F13 可视化讲解图形卡（figure 事件，可多次：图形随讲解步骤逐步出现） -->
        <MathFigure
          v-for="(f, fi) in msg.figures"
          :key="'fig' + fi"
          :figure="f"
          :streaming="msg.status === 'streaming'"
        />
```

## 补丁 2：`src/mock/server.js`（3 处）

### 2-a 新增 figure 构造助手（放在 `buildReply` 函数之后、`streamReply` 注释之前）

找到：

```js
/** 把回复拆成 token 片段流式下发 */
```

在其前插入：

```js
/* ===== F13 figure 事件构造助手（mock：抛物线 2 帧渐进揭示） ===== */
function svgDataUri(svg) {
  return 'data:image/svg+xml;base64,' + Buffer.from(svg, 'utf-8').toString('base64')
}

function parabolaFrames() {
  const body = (dots) => `<svg xmlns="http://www.w3.org/2000/svg" width="460" height="330" viewBox="0 0 460 330">
  <rect width="460" height="330" fill="#ffffff"/>
  <line x1="46" y1="169" x2="446" y2="169" stroke="#222222" stroke-width="1.3"/>
  <line x1="146" y1="16" x2="146" y2="296" stroke="#222222" stroke-width="1.3"/>
  <text x="452" y="161" font-size="13" font-style="italic" font-family="Georgia" text-anchor="start">x</text>
  <text x="158" y="12" font-size="13" font-style="italic" font-family="Georgia">y</text>
  <text x="136" y="184" font-size="11" font-family="Georgia" text-anchor="middle">O</text>
  <path d="M146 169 Q246 373 346 169" fill="none" stroke="#1a5fb4" stroke-width="1.9"/>
  ${dots}
</svg>`
  return [
    { data_uri: svgDataUri(body('')), label: '坐标系与曲线' },
    {
      data_uri: svgDataUri(
        body(
          '<circle cx="146" cy="169" r="3.5" fill="#c01c28" stroke="#ffffff"/><text x="154" y="165" font-size="12" fill="#c01c28" font-family="Georgia">(-1,0)</text>' +
          '<circle cx="346" cy="169" r="3.5" fill="#c01c28" stroke="#ffffff"/><text x="354" y="165" font-size="12" fill="#c01c28" font-family="Georgia">(3,0)</text>' +
          '<circle cx="246" cy="271" r="3.5" fill="#c01c28" stroke="#ffffff"/><text x="254" y="284" font-size="12" fill="#c01c28" font-family="Georgia">(1,-4)</text>'
        )
      ),
      label: '标注关键点',
    },
  ]
}
```

### 2-b `streamReply` 下发 figure 事件

找到：

```js
  if (reply.card) {
    push('card', reply.card, offset + 40)
  }
  if (reply.tail) {
    let t = offset + 120
```

替换为：

```js
  // F13：figure 事件在讲解 token 之后、卡片/收尾之前下发（图文顺序 = 讲解顺序）
  let figDelay = offset + 60
  for (const fig of reply.figures || []) {
    push('figure', fig, figDelay)
    figDelay += 180
  }
  if (reply.card) {
    push('card', reply.card, figDelay + 60)
  }
  if (reply.tail) {
    let t = figDelay + 180
```

并找到（同函数）：

```js
  push('done', {
    message_id: msgId,
    title: lead.replace(/[#*$]/g, '').slice(0, 16) || '新对话',
    usage: { tokens_in: 320, tokens_out: lead.length + (reply.tail || '').length },
    latency_ms: 4200,
    meta: { skill: reply.skill, confidence: 0.95 },
  }, offset + (reply.card ? 260 : 140))
```

替换为（done 必须在全部事件之后）：

```js
  const endDelay = figDelay + 200 + (reply.card ? 200 : 0) + (reply.tail ? Math.ceil(reply.tail.length / 8) * 20 : 0)
  push('done', {
    message_id: msgId,
    title: lead.replace(/[#*$]/g, '').slice(0, 16) || '新对话',
    usage: { tokens_in: 320, tokens_out: lead.length + (reply.tail || '').length },
    latency_ms: 4200,
    meta: { skill: reply.skill, confidence: 0.95 },
  }, endDelay)
```

### 2-c 默认 socratic 回复挂 figure + 历史持久化

找到（`buildReply` 默认分支的 return）：

```js
  /* 默认：苏格拉底引导（对齐 v4 演示） */
  return {
    skill: 'socratic_solver',
    thinking: '闭区间最值问题：f(x)=x³-3x，先求导找极值点，再代入端点比较，最后输出最大值最小值。',
    lead: '小婷，这道题确实需要一步步想清楚。\n\n我们先看题目要求的是什么——在闭区间 **$[-1, 3]$** 上找 **$f(x) = x^3 - 3x$** 的最大值和最小值。\n\n**你记得吗？求闭区间上函数的最值，通常会用到什么方法？**',
    card: null,
    tail: '想清楚这三步后告诉我，我帮你核对下一步，再给你变式巩固。',
  }
```

替换为：

```js
  /* 默认：苏格拉底引导（对齐 v4 演示）+ F13 figure 事件演示 */
  return {
    skill: 'socratic_solver',
    thinking: '闭区间最值问题：f(x)=x³-3x，先求导找极值点，再代入端点比较，最后输出最大值最小值。',
    lead: '小婷，这道题确实需要一步步想清楚。\n\n我们先看题目要求的是什么——在闭区间 **$[-1, 3]$** 上找 **$f(x) = x^3 - 3x$** 的最大值和最小值。\n\n**你记得吗？求闭区间上函数的最值，通常会用到什么方法？**',
    card: null,
    tail: '想清楚这三步后告诉我，我帮你核对下一步，再给你变式巩固。',
    figures: [
      {
        step_no: 1,
        caption: '先观察这条抛物线的形状，找找它与 x 轴的交点',
        frames: parabolaFrames(),
      },
    ],
  }
```

找到（历史持久化处）：

```js
          list.push({
            id: `am_${Date.now()}`, role: 'assistant', clientMsgId: cmid, createdAt: ts,
            envelope: {
              msg_id: `am_${Date.now()}`, meta: { skill: reply.skill, confidence: 0.95 },
              blocks: [{ type: 'markdown', content: reply.lead + (reply.tail ? '\n\n' + reply.tail : '') }],
            },
          })
```

替换为：

```js
          list.push({
            id: `am_${Date.now()}`, role: 'assistant', clientMsgId: cmid, createdAt: ts,
            envelope: {
              msg_id: `am_${Date.now()}`, meta: { skill: reply.skill, confidence: 0.95 },
              blocks: [
                { type: 'markdown', content: reply.lead + (reply.tail ? '\n\n' + reply.tail : '') },
                // F13：figure block 持久化（历史回显还原图形卡）
                ...(reply.figures || []).map((f) => ({ type: 'figure', ...f })),
              ],
            },
          })
```
