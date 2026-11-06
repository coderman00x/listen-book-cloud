import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 开发态：Vite dev server 在 :5173，通过 proxy 将 /api 转发到后端 :8000。
// 运行态：后端托管 frontend/dist，无需 proxy（同源）。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
});
