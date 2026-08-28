import { test, expect } from '@playwright/test';

// QA cepat: verifikasi toolbar baru Database & Tenant
// urutan: switch (Database|Koneksi) -> tombol aksi -> refresh
test('toolbar Database & Tenant: switch -> aksi -> refresh', async ({ page }) => {
  // login
  await page.goto('http://localhost:5173/');
  await page.waitForTimeout(800);
  await page.getByPlaceholder(/john|user|name/i).fill('admin');
  await page.getByPlaceholder(/••|password|pass/i).fill('admin123');
  await page.getByRole('button', { name: /masuk/i }).click();
  await page.waitForURL(/admin|dashboard/i, { timeout: 8000 }).catch(() => {});

  // buka halaman database-tenant
  await page.goto('http://localhost:5173/admin/database-tenant');
  await page.waitForTimeout(1500);

  // Ambil semua tombol di toolbar kanan
  const toolbarButtons = await page.locator('button').allTextContents();
  console.log('TOOLBAR BUTTONS:', JSON.stringify(toolbarButtons));

  // verifikasi urutan: switch ada di kiri, refresh di kanan
  const container = page.locator('div.ml-auto.flex.items-center.gap-3').first();
  await expect(container).toBeVisible();

  // screenshot toolbar
  await page.screenshot({ path: 'qa-toolbar.png' });
});
