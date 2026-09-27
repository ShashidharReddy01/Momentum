/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const API = process.env.MOMENTUM_API_URL ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src/momentum', import.meta.url)) },
  },
  server: {
    port: Number(process.env.PORT) || 5173,
    proxy: {
      '/api': { target: API, changeOrigin: false },
      '/healthz': { target: API },
      '/ws': { target: API, ws: true },
      '/.auth': { target: API },
    },
  },
  build: { outDir: 'dist', sourcemap: true },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
    // jsdom + userEvent interactions can run past the 5s default on a slower machine; the tests
    // themselves aren't slow, just tight on margin (real hangs still time out, just later).
    // 15 s was still too tight on a native Windows checkout: whole-suite runs failed on the
    // *timeout* in files the change under test never touched (S4.1.4/S4.1.5 both saw it), which
    // is a false red. A file-render test of the whole app takes ~10 s here on its own.
    testTimeout: 30000,
    // Native Windows (no container) creates a jsdom environment per file so slowly that running
    // many files concurrently starves userEvent's timers past testTimeout (momentum/cli.py and
    // tests/conftest.py have the same "Windows is different here" note, for psycopg). CI and dev
    // containers run Linux and keep full parallelism; only a native Windows checkout serializes.
    fileParallelism: process.platform !== 'win32',
  },
});
