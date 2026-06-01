import { expect, test } from '@playwright/test';

test('dashboard loads and exposes primary control surfaces', async ({ page }) => {
  const backendHealth = await page.request.get('http://127.0.0.1:8000/api/health');
  expect(backendHealth.ok()).toBeTruthy();

  await page.goto('/');

  await expect(page.getByRole('heading', { name: /campaign audit dashboard/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /overview/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /refresh data/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /creatives/i })).toBeVisible();
  await expect(page.getByText(/what needs attention now/i)).toBeVisible();
  await expect(page.getByText(/operator priority queue/i)).toBeVisible();
  await expect(page.getByText(/ask about your ads/i)).toBeVisible();
  await expect(page.getByPlaceholder(/which creative should we scale/i)).toBeVisible();

  await page.getByRole('button', { name: /alerts/i }).click();
  await expect(page.getByText(/new campaign watch/i)).toBeVisible();
  await expect(page.getByText(/current campaign decisions/i)).toBeVisible();
  await expect(page.getByText(/latest campaign health warnings/i)).toBeVisible();

  await page.getByRole('button', { name: /strategy/i }).click();
  await expect(page.getByRole('button', { name: /generate draft proposal/i })).toBeVisible();
  await expect(page.getByText(/review-only draft proposal/i)).toBeVisible();

  await page.getByRole('button', { name: /creatives/i }).click();
  await expect(page.getByText(/creative performance and quality/i)).toBeVisible();
  await expect(page.locator('.creative-thumb.has-video').first()).toBeVisible();
  await expect(page.locator('.creative-thumb img').first()).toBeVisible();
  await expect(page.getByText(/specialist read/i)).toBeVisible();
  await expect(page.getByText(/replicate signals/i)).toBeVisible();
  await expect(page.getByText(/next action/i)).toBeVisible();

  await page.getByRole('button', { name: /refresh data/i }).click();
  await expect(page.getByRole('heading', { name: /campaign audit dashboard/i })).toBeVisible();
});
