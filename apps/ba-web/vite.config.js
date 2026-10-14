import { defineConfig } from 'vite';
import { resolve } from 'path';

export default defineConfig({
  root: '.',
  // Served under /ba/ by the platform gateway; override with VITE_BASE for standalone dev.
  base: process.env.VITE_BASE || '/ba/',
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        chat: resolve(__dirname, 'chat.html'),
        va: resolve(__dirname, 'va.html'),
        wiki: resolve(__dirname, 'wiki.html'),
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    // Coder (and other reverse proxies) forward with a non-local Host header.
    allowedHosts: ['.coder.imespro.ai', 'localhost', '127.0.0.1'],
    proxy: {
      '/api': {
        target: process.env.API_PROXY || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
