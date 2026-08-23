// F13 demo 组件 SSR 冒烟验证：MathFigure 在无浏览器环境真实渲染出图形卡 DOM
// （依赖 demo/node_modules junction -> D:\frontend\node_modules 提供 vue/server-renderer）
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'
import App from './dist/App.js'

const html = await renderToString(createSSRApp(App))

const checks = [
  ['组件根节点', html.includes('math-figure')],
  ['步骤徽标', html.includes('步骤 1') && html.includes('步骤 2')],
  ['caption 文案', html.includes('先观察抛物线的开口方向与对称轴位置')],
  ['帧 1 label（坐标系与曲线）', html.includes('坐标系与曲线')],
  ['帧 2 label（标注关键点）', html.includes('标注关键点')],
  ['立体几何帧 label（几何体轮廓）', html.includes('几何体轮廓')],
  ['帧数据 data URI', html.includes('data:image/svg+xml;base64,')],
  ['帧圆点导航', html.includes('mf-dot')],
  ['重播按钮', html.includes('重播')],
  ['纯文字对照开关', html.includes('可视化讲解')],
]

let fail = 0
for (const [name, ok] of checks) {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}`)
  if (!ok) fail++
}
console.log(`\nSSR HTML 长度: ${html.length}`)
process.exit(fail ? 1 : 0)
