import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  use: {
    baseURL: 'http://localhost:5173',
    headless: true,
    screenshot: 'only-on-failure',
  },
  // Frontend & backend diasumsikan sudah berjalan (dev server user).
  // Jalankan manual: npm run dev + uvicorn.
});
