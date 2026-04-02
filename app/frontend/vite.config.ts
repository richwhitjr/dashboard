import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { execSync } from 'child_process'

const backendPort = process.env.BACKEND_PORT || '8000'

let appVersion = 'dev'
try {
  appVersion = execSync('git describe --tags --always', { encoding: 'utf8' }).trim()
} catch {
  // ignore
}

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(appVersion),
  },
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'xterm': ['@xterm/xterm', '@xterm/addon-fit', '@xterm/addon-serialize', '@xterm/addon-web-links'],
          'markdown': ['react-markdown', 'remark-gfm'],
          'vendor': ['react', 'react-dom', 'react-router-dom', '@tanstack/react-query'],
        },
      },
    },
  },
  server: {
    proxy: {
      '/api': {
        target: `http://localhost:${backendPort}`,
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
