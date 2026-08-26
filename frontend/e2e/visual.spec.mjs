import { test, expect } from '@playwright/test';

/**
 * Visual regression: bandingkan tampilan tiap halaman admin
 * terhadap baseline. Jalankan `npx playwright test --update-snapshots`
 * saat perubahan UI memang disengaja.
 */
async function login(page) {
  await page.goto('/admin/perusahaan-cabang');
  if (await page.locator('nav').count()) return;
  await page.locator('input[type="text"], input:not([type])').first().fill('admin');
  await page.locator('input[type="password"]').fill('admin123');
  await page.getByRole('button', { name: /masuk/i }).click();
  await expect(page.locator('nav')).toBeVisible({ timeout: 10_000 });
}

const PAGES = [
  ['perusahaan-cabang', 'perusahaan'],
  ['database-tenant', 'database-tenant'],
  ['ai-config', 'ai-config'],
  ['pengguna', 'pengguna'],
  ['audit-log', 'audit-log'],
];

for (const [slug] of PAGES) {
  test(`visual: ${slug}`, async ({ page }) => {
    await login(page);
    await page.goto(`/admin/${slug}`);
    await expect(page.locator('main')).toBeVisible();
    await page.waitForTimeout(600); // animasi masuk selesai
    await expect(page.locator('main')).toHaveScreenshot({ maxDiffPixelRatio: 0.02 });
  });
}
