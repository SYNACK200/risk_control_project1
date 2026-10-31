import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 生产构建可用 VITE_BASE=/bank/ 让银行侧挂在子路径下
export default defineConfig({
  base: process.env.VITE_BASE || '/',
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5174,
    strictPort: true,
    proxy: { '/api': process.env.API_TARGET || 'http://127.0.0.1:8010' },
  },
});
