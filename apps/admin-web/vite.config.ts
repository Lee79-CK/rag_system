import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Closed-network: build-time deps come from the public npm registry (local dev only),
// but the app makes NO external runtime calls. Every request targets relative `/api/...`,
// which the ingress (prod) or this dev proxy (local) forwards to admin-api.
// admin-api dev port: 8003 (docs/TDD.md §7.6).
export default defineConfig({
  base: '/',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8003',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
