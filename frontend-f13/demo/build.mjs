import { readFileSync, writeFileSync, mkdirSync, copyFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse, compileScript, compileStyle } from '@vue/compiler-sfc'

// 零 spawn 构建：@vue/compiler-sfc 直接编译 SFC -> ES 模块（沙箱禁 piped stdio，不能用 vite/esbuild）
const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = join(HERE, 'src')
const DIST = join(HERE, 'dist')

const IDS = { 'App.vue': 'demo-app', 'MathFigure.vue': 'math-figure', 'UiIcon.vue': 'ui-icon' }

// 每个源文件的别名导入 -> 相对产物位置的路径
const IMPORT_MAPS = {
  'App.vue': { '@/components/chat/MathFigure.vue': './components/chat/MathFigure.js' },
  'components/chat/MathFigure.vue': { '@/components/common/UiIcon.vue': '../common/UiIcon.js' },
  'components/common/UiIcon.vue': {},
}

function buildSfc(rel) {
  const source = readFileSync(join(SRC, rel), 'utf-8')
  const { descriptor, errors } = parse(source, { filename: rel })
  if (errors?.length) throw new Error(`${rel} 解析失败: ${errors[0].message}`)
  const id = IDS[rel.split('/').pop()] || 'sfc'
  const scoped = descriptor.styles.some((s) => s.scoped)
  const script = compileScript(descriptor, { id, inlineTemplate: true })
  let code = script.content
  // import 重写：别名 -> 相对产物路径（按源文件位置映射）
  for (const [from, to] of Object.entries(IMPORT_MAPS[rel] || {})) {
    code = code.replaceAll(from, to)
  }
  let css = ''
  for (const st of descriptor.styles) {
    const r = compileStyle({ source: st.content, filename: rel, id, scoped: st.scoped })
    if (r.errors?.length) throw new Error(`${rel} 样式编译失败: ${r.errors[0].message}`)
    css += r.code + '\n'
  }
  return { code, css }
}

mkdirSync(join(DIST, 'components', 'chat'), { recursive: true })
mkdirSync(join(DIST, 'components', 'common'), { recursive: true })

let allCss = ''
for (const rel of [
  'components/common/UiIcon.vue',
  'components/chat/MathFigure.vue',
  'App.vue',
]) {
  const { code, css } = buildSfc(rel)
  const out = join(DIST, rel.replace(/\.vue$/, '.js'))
  writeFileSync(out, code, 'utf-8')
  allCss += `/* === ${rel} === */\n${css}\n`
  console.log(`built ${rel} -> ${out} (${code.length} chars)`)

// App.vue 产物里的 figureData 相对引用修正
  if (rel === 'App.vue') {
    let appCode = readFileSync(out, 'utf-8')
    appCode = appCode.replaceAll("./figureData", "./figureData.js")
    writeFileSync(out, appCode, 'utf-8')
  }
}

writeFileSync(join(DIST, 'style.css'), allCss, 'utf-8')
copyFileSync(join(SRC, 'figureData.js'), join(DIST, 'figureData.js'))
console.log('built style.css + figureData.js ->', DIST)
