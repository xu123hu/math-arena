import http from 'node:http'
import { readFileSync, existsSync } from 'node:fs'
import { dirname, join, normalize } from 'node:path'
import { fileURLToPath } from 'node:url'

// 极简静态服务器（进程内，零 spawn）：demo 产物 + 前端 vue 运行时（只读复用）
const HERE = dirname(fileURLToPath(import.meta.url))
const VUE_RUNTIME = 'D:/frontend/node_modules/vue/dist/vue.esm-browser.js'

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
}

function send(res, status, body, type) {
  res.writeHead(status, { 'Content-Type': type })
  res.end(body)
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1')
  let path = decodeURIComponent(url.pathname)

  if (path === '/vendor/vue.esm-browser.js') {
    return send(res, 200, readFileSync(VUE_RUNTIME), MIME['.js'])
  }
  if (path === '/style.css') return send(res, 200, readFileSync(join(HERE, 'dist/style.css')), MIME['.css'])
  if (path === '/demo.css') return send(res, 200, readFileSync(join(HERE, 'src/demo.css')), MIME['.css'])
  if (path === '/') path = '/index.html'
  if (path === '/index.html') return send(res, 200, readFileSync(join(HERE, 'index.html')), MIME['.html'])
  if (path.startsWith('/src/')) path = '/dist/' + path.slice(5)
  const file = join(HERE, normalize(path).replace(/^[/\\]/, ''))
  if (existsSync(file) && file.startsWith(HERE)) {
    const ext = path.slice(path.lastIndexOf('.'))
    return send(res, 200, readFileSync(file), MIME[ext] || 'application/octet-stream')
  }
  send(res, 404, 'not found', 'text/plain')
})

server.listen(5210, '127.0.0.1', () => console.log('demo server: http://127.0.0.1:5210'))
