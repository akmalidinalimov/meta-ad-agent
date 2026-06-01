import { expect, test } from '@playwright/test';

test('dashboard loads and exposes primary control surfaces', async ({ page }) => {
  const backendHealth = await page.request.get('http://127.0.0.1:8000/api/health');
  expect(backendHealth.ok()).toBeTruthy();

  await page.goto('/');

  await expect(page.getByRole('heading', { name: /campaign audit dashboard/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /overview/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /refresh data/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /creatives/i })).toBeVisible();
  await expect(page.getByText(/ask about your ads/i)).toBeVisible();
  await expect(page.getByPlaceholder(/which creative should we scale/i)).toBeVisible();

  await page.getByRole('button', { name: /alerts/i }).click();
  await expect(page.getByText(/new campaign watch/i)).toBeVisible();
  await expect(page.getByText(/current campaign decisions/i)).toBeVisible();
  await expect(page.getByText(/latest campaign health warnings/i)).toBeVisible();

  await page.getByRole('button', { name: /refresh data/i }).click();
  await expect(page.getByRole('heading', { name: /campaign audit dashboard/i })).toBeVisible();
});
