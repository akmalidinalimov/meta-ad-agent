import { expect, test } from '@playwright/test';

test('dashboard loads and exposes primary control surfaces', async ({ page }) => {
  const backendHealth = await page.request.get('http://127.0.0.1:8000/api/health');
  expect(backendHealth.ok()).toBeTruthy();

  await page.goto('/', { waitUntil: 'domcontentloaded' });

  // The front door is now the chat-first campaign setup view.
  await expect(page.getByRole('heading', { level: 1, name: /set up a campaign by chatting/i })).toBeVisible();
  const nav = page.locator('.app-nav');
  await expect(nav.getByRole('button', { name: /chat/i })).toBeVisible();
  await expect(nav.getByRole('button', { name: /monitor/i })).toBeVisible();
  await expect(nav.getByRole('button', { name: /command center/i })).toBeVisible();
  await expect(nav.getByRole('button', { name: /rankings/i })).toBeVisible();
  await expect(nav.getByRole('button', { name: /settings/i })).toBeVisible();
  await expect(nav.getByRole('button')).toHaveCount(5);
  await expect(nav.getByRole('button', { name: /creatives/i })).toHaveCount(0);
  await expect(nav.getByRole('button', { name: /funnel/i })).toHaveCount(0);
  await expect(nav.getByRole('button', { name: /agent office/i })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /refresh data/i })).toBeVisible();
  // Chat front door surfaces the conversation + starter prompts.
  await expect(page.getByRole('heading', { name: /ask about your ads/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /plan a 3-vsl launch/i })).toBeVisible();

  // The Monitor view carries the audit + priority surfaces.
  await nav.getByRole('button', { name: /monitor/i }).click();
  await expect(page.getByRole('heading', { name: /campaign audit dashboard/i })).toBeVisible();
  await expect(page.getByText(/action needed|watch closely|healthy/i)).toBeVisible();
  await expect(page.getByText(/best current levers/i)).toBeVisible();
  await expect(page.getByText(/what needs attention now/i)).toBeVisible();
  await expect(page.getByText(/operator priority queue/i)).toBeVisible();

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

  await nav.getByRole('button', { name: /command center/i }).click();
  await expect(page.getByText(/tell the agent what outcome you want/i)).toBeVisible();
  await expect(page.getByText(/ask about your ads/i)).toBeVisible();
  await expect(page.getByPlaceholder(/which creative should we scale/i)).toBeVisible();
  await expect(page.getByText(/agent availability/i)).toBeVisible();
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
  await page.getByRole('button', { name: 'Create paused packet', exact: true }).click();
  await expect(page.locator('.implementation-result')).toContainText(/paused campaign approval created/i);
  await expect(page.getByText(/cannot publish or spend/i)).toBeVisible();
  await expect(page.getByText(/edit campaign playbook and task metadata/i)).toBeVisible();

  await nav.getByRole('button', { name: /rankings/i }).click();
  await expect(page.getByText(/campaign ranking/i)).toBeVisible();
  await expect(page.getByText(/creative ranking/i)).toBeVisible();
  await expect(page.getByText(/audience \/ ad set ranking/i)).toBeVisible();
  await expect(page.getByText(/placement ranking/i)).toBeVisible();

  await nav.getByRole('button', { name: /settings/i }).click();
  await expect(page.getByText(/marketing api status/i)).toBeVisible();
  await expect(page.getByText(/tracking diagnostics/i)).toBeVisible();
  await expect(page.getByText(/meta settings audit/i)).toBeVisible();

  await page.getByRole('button', { name: /refresh data/i }).click();
  await nav.getByRole('button', { name: /monitor/i }).click();
  await expect(page.getByRole('heading', { name: /campaign audit dashboard/i })).toBeVisible();
});
