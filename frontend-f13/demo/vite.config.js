import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// 依赖解析：node_modules junction -> D:\frontend\node_modules（复用前端既有 vue/vite 依赖，零新装）
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: { port: 5199, host: '127.0.0.1' },
})
