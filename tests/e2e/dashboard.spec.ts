import { expect, test } from '@playwright/test';

test('dashboard loads and exposes primary control surfaces', async ({ page }) => {
  const backendHealth = await page.request.get('http://127.0.0.1:8000/api/health');
  expect(backendHealth.ok()).toBeTruthy();

  await page.goto('/', { waitUntil: 'domcontentloaded' });

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
  const strategyResponse = await page.request.post('http://127.0.0.1:8000/api/strategy/generate', {
    data: {
      playbook: {
        id: 'e2e_playbook',
        name: 'E2E launch',
        primarySuccessMetric: 'telegram_start',
        segments: [
          {
            id: 'income',
            name: 'Income',
            startingBudgetUsd: 100,
            locations: ['Uzbekistan'],
            placements: ['instagram_reels'],
            interests: ['Artificial intelligence'],
          },
        ],
        rules: { startingBudgetUsd: 100, maxDailyBudgetUsd: 300, requiresApprovalForExecution: true },
        approvalChannels: ['dashboard'],
      },
    },
  });
  expect(strategyResponse.ok()).toBeTruthy();
  const strategyPayload = await strategyResponse.json();
  expect(strategyPayload.strategy.launchPacket.decision).toBe('approval_required');
  expect(strategyPayload.strategy.launchPacket.monitoringPlan.cadenceHours).toBe(4);

  await page.getByRole('button', { name: /command center/i }).click();
  await expect(page.getByText(/regression checklist/i)).toBeVisible();
  await expect(page.getByText(/completion readiness/i)).toBeVisible();
  await expect(page.getByText(/agent availability/i)).toBeVisible();

  await page.getByRole('button', { name: /agent office/i }).click();
  await expect(page.getByText(/multi-agent strategy council/i)).toBeVisible();
  await expect(page.getByText(/watch agents debate the campaign/i)).toBeVisible();
  await expect(page.getByText(/what is happening now/i)).toBeVisible();
  await expect(page.locator('.agent-desk')).toHaveCount(10);
  const officeBox = await page.locator('.agent-office-map').boundingBox();
  expect(officeBox).toBeTruthy();
  const agentBoxes = await page.locator('.agent-desk').evaluateAll((nodes) =>
    nodes.map((node) => {
      const box = node.getBoundingClientRect();
      return { left: box.left, right: box.right, top: box.top, bottom: box.bottom };
    }),
  );
  for (const box of agentBoxes) {
    expect(box.left).toBeGreaterThanOrEqual(officeBox!.x - 1);
    expect(box.top).toBeGreaterThanOrEqual(officeBox!.y - 1);
    expect(box.right).toBeLessThanOrEqual(officeBox!.x + officeBox!.width + 1);
    expect(box.bottom).toBeLessThanOrEqual(officeBox!.y + officeBox!.height + 1);
  }
  await page.getByRole('button', { name: /run council/i }).click();
  await expect(page.getByText(/council session generated/i)).toBeVisible();
  await expect(page.getByText(/paused draft allowed/i)).toBeVisible();
  await expect(page.getByText(/timeline replay/i)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Pause', exact: true })).toBeVisible();
  await expect(page.locator('.moving-agent')).toBeVisible();
  await expect(page.locator('.agent-desk.speaker')).toBeVisible();
  await expect(page.locator('.agent-desk.receiver')).toBeVisible();
  await expect(page.locator('.active-exchange-card')).toContainText(/round/i);
  await page.getByRole('button', { name: 'Implemented', exact: true }).click();
  await expect(page.locator('.implementation-result')).toContainText(/paused campaign approval created/i);
  await expect(page.getByText(/cannot publish or spend/i)).toBeVisible();

  await page.getByRole('button', { name: 'Creatives', exact: true }).click();
  await expect(page.getByText(/creative performance and quality/i)).toBeVisible();
  await expect(page.locator('.creative-thumb.has-video').first()).toBeVisible();
  await expect(page.locator('.creative-thumb img').first()).toBeVisible();
  await expect(page.getByText(/specialist read/i)).toBeVisible();
  await expect(page.getByText(/replicate signals/i)).toBeVisible();
  await expect(page.getByText(/next action/i)).toBeVisible();

  await page.getByRole('button', { name: /refresh data/i }).click();
  await expect(page.getByRole('heading', { name: /campaign audit dashboard/i })).toBeVisible();
});
