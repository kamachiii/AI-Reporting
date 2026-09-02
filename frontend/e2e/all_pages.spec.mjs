import { test, expect } from '@playwright/test';

async function performLogin(page, username, password) {
  await page.goto('/');
  await page.evaluate(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
  await page.goto('/');
  await page.locator('input[type="text"], input:not([type])').first().fill(username);
  await page.locator('input[type="password"]').fill(password);
  await page.getByRole('button', { name: /masuk/i }).click();
  await page.waitForTimeout(1000);
}

test.describe('Comprehensive End-to-End Page Testing', () => {

  test('1. Halaman Login: validasi login gagal & sukses admin', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
    await page.goto('/');
    await expect(page.getByRole('heading', { name: /dms ai platform/i })).toBeVisible();

    // Password salah
    await page.locator('input[type="text"], input:not([type])').first().fill('admin');
    await page.locator('input[type="password"]').fill('passwordsalah123');
    await page.getByRole('button', { name: /masuk/i }).click();
    await expect(page.getByText(/gagal|salah|invalid|unauthorized/i)).toBeVisible({ timeout: 5000 });

    // Password benar
    await page.locator('input[type="password"]').fill('admin123');
    await page.getByRole('button', { name: /masuk/i }).click();
    await expect(page).toHaveURL(/admin\/perusahaan-cabang/, { timeout: 10000 });
    await expect(page.locator('aside')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Perusahaan & Cabang' })).toBeVisible();
  });

  test('2. Admin: Halaman Perusahaan & Cabang', async ({ page }) => {
    await performLogin(page, 'admin', 'admin123');
    await page.goto('/admin/perusahaan-cabang');
    await expect(page.getByRole('heading', { name: 'Perusahaan & Cabang' })).toBeVisible();

    // Modal Tambah Perusahaan
    await page.getByRole('button', { name: /tambah perusahaan/i }).click();
    await expect(page.locator('.fixed.inset-0').last()).toBeVisible();
    await page.keyboard.press('Escape');

    // Switch ke Tab Cabang / Dealer
    await page.getByRole('button', { name: 'Cabang / Dealer' }).click();
    await expect(page.getByRole('button', { name: /tambah cabang/i })).toBeVisible();
  });

  test('3. Admin: Halaman Database & Tenant', async ({ page }) => {
    await performLogin(page, 'admin', 'admin123');
    await page.goto('/admin/database-tenant');
    await expect(page.getByRole('heading', { name: 'Database & Tenant' })).toBeVisible();
    await expect(page.getByText(/database/i).first()).toBeVisible();
  });

  test('4. Admin: Halaman Penyedia & Model AI', async ({ page }) => {
    await performLogin(page, 'admin', 'admin123');
    await page.goto('/admin/ai-config');
    await expect(page.getByRole('heading', { name: 'Penyedia & Model AI' })).toBeVisible();
    await expect(page.getByRole('button', { name: /tambah config ai/i })).toBeVisible();
    await expect(page.locator('#aiconfig-search')).toBeVisible();
  });

  test('5. Admin: Halaman Pengguna & Izin', async ({ page }) => {
    await performLogin(page, 'admin', 'admin123');
    await page.goto('/admin/pengguna');
    await expect(page.getByRole('heading', { name: 'Pengguna & Izin' })).toBeVisible();
    await expect(page.getByRole('button', { name: /tambah user/i })).toBeVisible();
    await expect(page.locator('#user-search')).toBeVisible();
  });

  test('6. Admin: Halaman Audit Log & Monitoring', async ({ page }) => {
    await performLogin(page, 'admin', 'admin123');
    await page.goto('/admin/audit-log');
    await expect(page.getByRole('heading', { name: 'Audit Log & Monitoring' })).toBeVisible();
    await expect(page.locator('table, .border, .divide-y').first()).toBeVisible();
  });

  test('7. User Workspace: Login user, status cabang, template pertanyaan, & logout', async ({ page }) => {
    await performLogin(page, 'user_jkt', 'user123');

    // Verifikasi tampilan User Workspace
    await expect(page.locator('input[aria-label="Pertanyaan"]')).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/JKT_01|Jakarta/i).first()).toBeVisible();

    // Verifikasi tombol saran pertanyaan ada
    await expect(page.getByText('Penjualan bulan ini')).toBeVisible();

    // Test tombol logout user
    await page.getByRole('button', { name: /keluar/i }).click();
    await expect(page.getByRole('button', { name: /masuk/i })).toBeVisible({ timeout: 5000 });
  });

});
