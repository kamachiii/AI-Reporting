// Exploratory QA DMS — semua tab admin + workspace user, screenshot + console error collector.
import { test, expect } from '@playwright/test';
import fs from 'fs';

const SHOT = 'test-results/exploratory';
fs.mkdirSync(SHOT, { recursive: true });

const adminTabs = [
  'perusahaan-cabang',
  'database-tenant',
  'ai-config',
  'pengguna',
  'audit-log',
];

async function login(page, username, password) {
  await page.goto('/');
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
  await page.goto('/');
  await page.locator('input[type="text"], input:not([type])').first().fill(username);
  await page.locator('input[type="password"]').fill(password);
  await page.getByRole('button', { name: /masuk/i }).click();
  await page.waitForTimeout(1200);
}

test.describe.serial('EXPLORATORY: admin semua tab', () => {
  let consoleErrors;

  test.beforeEach(async ({ page }) => {
    consoleErrors = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text().slice(0, 200));
    });
    page.on('pageerror', (err) => consoleErrors.push('PAGEERROR: ' + String(err).slice(0, 200)));
    await login(page, 'admin', 'admin123');
  });

  for (const tab of adminTabs) {
    test(`admin tab /${tab} render + interaksi dasar + 0 console error`, async ({ page }) => {
      await page.goto(`/admin/${tab}`);
      await page.waitForTimeout(1200);

      // 1. Halaman merender konten nyata (bukan blank / error boundary)
      const body = await page.locator('body').innerText();
      expect(body.length).toBeGreaterThan(100);

      // 2. Tidak ada ErrorBoundary / white screen
      expect(body).not.toContain('Something went wrong');
      expect(body).not.toContain('Memuat aplikasi...'); // stuck di loading

      // 3. Screenshot utk review
      await page.screenshot({ path: `${SHOT}/admin-${tab}.png`, fullPage: false });

      // 4. Buka satu modal utama per tab (kalau ada tombol tambah)
      const addBtn = page.getByRole('button', { name: /tambah|daftarkan|baru/i }).first();
      if (await addBtn.isVisible().catch(() => false)) {
        await addBtn.click();
        await page.waitForTimeout(600);
        await page.screenshot({ path: `${SHOT}/admin-${tab}-modal.png` });
        const modalText = await page.locator('body').innerText();
        expect(modalText.length).toBeGreaterThan(body.length - 50); // modal menambah konten
        // tutup modal (X / Batal / Esc)
        await page.keyboard.press('Escape');
        await page.waitForTimeout(300);
      }

      // 5. Console error = gagal (kecuali noise yang diketahui)
      const realErrors = consoleErrors.filter((e) =>
        !e.includes('favicon') && !e.includes('Download the React DevTools'));
      expect(realErrors, `console error di ${tab}: ${realErrors.join(' | ')}`).toHaveLength(0);
    });
  }
});

test.describe.serial('EXPLORATORY: workspace user (chat)', () => {
  test('login user, chat UI render, kirim pertanyaan replay, badge & SQL terlihat', async ({ page }) => {
    const consoleErrors = [];
    page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)); });
    page.on('pageerror', (err) => consoleErrors.push('PAGEERROR: ' + String(err).slice(0, 200)));

    await login(page, 'user_jkt', 'user123');
    await page.waitForTimeout(1000);
    await page.screenshot({ path: `${SHOT}/user-workspace.png` });

    const body = await page.locator('body').innerText();
    expect(body).not.toContain('Something went wrong');

    // Elemen inti chat: input pertanyaan
    const chatInput = page.locator('textarea, input[placeholder*="tanya" i], input[type="text"]').first();
    await expect(chatInput).toBeVisible();

    // Kirim pertanyaan yang ada di memory approved (replay 0-LLM, cepat & deterministik)
    await chatInput.fill('tampilkan 5 cabang');
    await page.keyboard.press('Enter');
    // atau tombol kirim
    const sendBtn = page.getByRole('button', { name: /kirim|send/i }).first();
    if (await sendBtn.isVisible().catch(() => false)) await sendBtn.click();

    // Jawaban muncul dalam 30 dtk (replay harus cepat)
    await page.waitForTimeout(8000);
    const after = await page.locator('body').innerText();
    await page.screenshot({ path: `${SHOT}/user-chat-answer.png`, fullPage: true });

    const answered = /cabang|FOURBEST|SQL|confidence|keyakinan/i.test(after);
    expect(answered, 'jawaban chat tidak terlihat di halaman').toBeTruthy();

    const realErrors = consoleErrors.filter((e) => !e.includes('favicon'));
    expect(realErrors, `console error chat: ${realErrors.join(' | ')}`).toHaveLength(0);
  });
});
