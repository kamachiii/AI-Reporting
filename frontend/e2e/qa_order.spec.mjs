
import { test, expect } from '@playwright/test';

test('toolbar order X positions', async ({ page }) => {
  await page.goto('http://localhost:5173/');
  await page.waitForTimeout(600);
  await page.getByPlaceholder(/john/i).fill('admin');
  await page.getByPlaceholder(/••|pass/i).fill('admin123');
  await page.getByRole('button', { name: /masuk/i }).click();
  await page.waitForTimeout(1500);
  await page.goto('http://localhost:5173/admin/database-tenant');
  await page.waitForTimeout(1800);

  const container = page.locator('div.ml-auto.flex.items-center.gap-3').first();
  const boxes = await container.locator('button').evaluateAll(btns =>
    btns.map(b => ({ text: b.textContent.trim(), x: b.getBoundingClientRect().x }))
  );
  console.log('ORDER:', JSON.stringify(boxes));
  // verifikasi: urutan x ascending = switch, aksi, refresh
  expect(boxes.length).toBeGreaterThanOrEqual(3);
  const xs = boxes.map(b => b.x);
  expect([...xs].sort((a,b) => a-b)).toEqual(xs);
});
