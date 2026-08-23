<template>
  <!-- F13 MathFigure 组件独立演示：模拟对话气泡 + figure 事件渲染
       图形数据由后端 figure_renderer 真实渲染生成（figureData.js）。 -->
  <div class="page">
    <h1>F13 可视化讲解 · MathFigure 组件演示</h1>
    <p class="sub">
      数据源：后端 figure_renderer 确定性渲染（scripts/render_f13_samples.py）→
      figure 事件 → 本组件帧渐进揭示。流式结束后自动播放帧序列，可点帧圆点/重播。
    </p>

    <div class="toolbar">
      <label class="toggle">
        <input v-model="showFigures" type="checkbox" />
        <span>可视化讲解</span>
      </label>
      <button class="btn" @click="simulate">模拟一次对话流（2.5s 后 done）</button>
      <span v-if="streaming" class="state">● 流式输出中…</span>
      <span v-else class="state ok">流已结束（done），帧自动播放</span>
    </div>

    <div class="chat">
      <!-- 用户气泡 -->
      <div class="row user">
        <div class="bubble ub">作出函数 $y=x^2-2x-3$ 的图像，并求图像与 $x$ 轴交点的坐标</div>
      </div>

      <!-- AI 气泡：纯文字讲解（对照） -->
      <div v-if="!showFigures" class="row ai">
        <div class="avatar">π</div>
        <div class="bubble ab">
          先回忆一下：二次函数的图像是什么形状？它的开口方向由谁决定？
          你能求出它的顶点坐标吗？
        </div>
      </div>

      <!-- AI 气泡：可视化讲解 -->
      <div v-else class="row ai">
        <div class="avatar">π</div>
        <div class="ai-col">
          <div class="bubble ab">
            <p>先回忆一下：二次函数的图像是什么形状？它的开口方向由谁决定？</p>
            <p class="dim">（AI 讲到这里时，figure 事件随讲解流下发 👇）</p>

            <!-- F13：figure 事件渲染（与 MessageBubble.vue 集成方式一致） -->
            <MathFigure
              v-for="(f, i) in figures"
              :key="'fig' + i + streamSeq"
              :figure="f"
              :streaming="streaming"
            />
          </div>
        </div>
      </div>
    </div>

    <footer>MathFigure.vue · 帧圆点导航 / 自动播放 / 重播 · 零新依赖（Vue3 + CSS 变量）</footer>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import MathFigure from '@/components/chat/MathFigure.vue'
import { FIGURES } from './figureData'

const showFigures = ref(true)
const streaming = ref(true)
const streamSeq = ref(0)
const figures = ref(FIGURES)

// 模拟 SSE 流：初始 streaming=true（figure 随流出现，展示帧 0），
// 2.5s 后 done → streaming=false → MathFigure 自动播放帧序列
function simulate() {
  streamSeq.value += 1 // 重建组件（重新从帧 0 开始，演示流式到达）
  streaming.value = true
  figures.value = FIGURES
  setTimeout(() => { streaming.value = false }, 2500)
}
</script>

<style scoped>
.page { max-width: 780px; margin: 0 auto; padding: 24px 16px 40px; font-family: var(--font); }
h1 { font-size: 20px; margin: 0 0 6px; color: var(--text-primary); }
.sub { font-size: 12px; color: var(--text-muted); margin: 0 0 16px; line-height: 1.7; }
.toolbar { display: flex; align-items: center; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; }
.toggle { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-secondary); cursor: pointer; }
.btn {
  padding: 6px 14px; border-radius: var(--radius-md); border: 1px solid var(--primary-border);
  background: var(--bg-white); color: var(--primary); font-size: 13px; cursor: pointer;
  font-family: var(--font);
}
.btn:hover { background: var(--primary-subtle); }
.state { font-size: 12px; color: #d97706; }
.state.ok { color: #059669; }
.chat { display: flex; flex-direction: column; gap: 14px; }
.row { display: flex; }
.row.user { justify-content: flex-end; }
.row.ai { justify-content: flex-start; align-items: flex-start; gap: 8px; }
.bubble {
  padding: 10px 14px; border-radius: var(--radius-lg); font-size: 14px; line-height: 1.7;
  max-width: 86%;
}
.ub { background: var(--primary); color: #fff; border-bottom-right-radius: var(--radius-sm); }
.ab { background: var(--bg-white); border: 1px solid var(--border); border-top-left-radius: var(--radius-sm); }
.ab p { margin: 0 0 6px; }
.ab .dim { color: var(--text-muted); font-size: 12px; }
.avatar {
  width: 30px; height: 30px; border-radius: var(--radius-md); flex-shrink: 0;
  background: var(--primary); color: #fff; display: flex; align-items: center;
  justify-content: center; font-weight: 600; font-family: Georgia, serif; margin-top: 2px;
}
.ai-col { max-width: 92%; min-width: 0; flex: 1; }
footer { margin-top: 32px; font-size: 11px; color: var(--text-muted); }
</style>
