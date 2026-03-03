import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0', // 允许局域网访问
    port: 3666,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8088', changeOrigin: true },
      '/geoserver': { target: 'http://127.0.0.1:8080', changeOrigin: true },
    },
  },
})
