import { test, expect } from '@playwright/test';

/**
 * E2E: alur admin inti.
 * Prasyarat: dev server (5173) + backend (8000) berjalan.
 */

async function login(page) {
  await page.goto('/admin/perusahaan-cabang');
  // Jika sudah login, langsung kembali
  if (!page.url().includes('login') && await page.locator('nav').count()) return;

  await page.locator('input[type="text"], input:not([type])').first().fill('admin');
  await page.locator('input[type="password"]').fill('admin123');
  await page.getByRole('button', { name: /masuk/i }).click();
  await expect(page.locator('nav')).toBeVisible({ timeout: 10_000 });
}

test.describe('Admin — Perusahaan & Cabang', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('halaman perusahaan render tabel', async ({ page }) => {
    await expect(page).toHaveURL(/admin\/perusahaan-cabang/);
    await expect(page.getByText('AutoDealer Corp')).toBeVisible();
  });

  test('switch ke tab Cabang/Dealer tanpa crash', async ({ page }) => {
    const err = [];
    page.on('pageerror', (e) => err.push(e.message));
    await page.getByRole('button', { name: 'Cabang / Dealer' }).click();
    // panel registry + tombol tambah cabang harus tampak
        await expect(page.getByRole('button', { name: /tambah cabang/i })).toBeVisible();
    expect(err, 'tidak boleh ada page error').toEqual([]);
  });

  test('modal Tambah Perusahaan terbuka & bisa ditutup', async ({ page }) => {
    await page.getByRole('button', { name: /tambah perusahaan/i }).click();
    await expect(page.locator('.fixed.inset-0').last()).toBeVisible();
    await page.keyboard.press('Escape');
  });

  test('routing: setiap menu mengubah URL', async ({ page }) => {
    for (const [label, path] of [
      ['Database & Tenant', 'database-tenant'],
      ['Penyedia & Model AI', 'ai-config'],
      ['Pengguna & Izin', 'pengguna'],
      ['Audit Log & Monitoring', 'audit-log'],
      ['Perusahaan & Cabang', 'perusahaan-cabang'],
    ]) {
      await page.locator('nav').getByRole('button', { name: label }).click();
      await expect(page).toHaveURL(new RegExp(path));
    }
  });

  test('URL ngawur redirect ke halaman pertama', async ({ page }) => {
    await page.goto('/admin/halaman-ngawur');
    await page.waitForURL(/perusahaan-cabang/, { timeout: 10_000 });
    await expect(page).toHaveURL(/perusahaan-cabang/);
  });
});
