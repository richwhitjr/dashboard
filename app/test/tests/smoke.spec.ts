import { test, expect } from '@playwright/test';

// Smoke tests: top-level UX & navigation
// These verify the app loads and core pages are reachable.
// Connector-dependent pages (Email, Slack, Notion, etc.) are NOT tested
// since they depend on auth state.

test.describe('app loads', () => {
  test('sidebar is visible on load', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
  });

  test('dashboard renders', async ({ page }) => {
    await page.goto('/');
    // Briefing page shows "Good morning/afternoon/evening" greeting
    await expect(page.locator('h1:has-text("Good")')).toBeVisible({ timeout: 10000 });
  });
});

test.describe('sidebar navigation', () => {
  // These pages are always visible regardless of connector state
  const corePages = [
    { link: 'Thoughts', heading: 'Thoughts' },
    { link: 'Issues', heading: 'Issues' },
    { link: 'Docs', heading: 'Docs' },
    { link: 'People', heading: 'People' },
  ];

  for (const { link, heading } of corePages) {
    test(`navigate to ${link}`, async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('.sidebar');
      await page.locator(`.sidebar nav a:has-text("${link}")`).first().click();
      await expect(page.locator(`h1:has-text("${heading}")`)).toBeVisible({ timeout: 10000 });
    });
  }

  test('navigate to Settings', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.sidebar');
    await page.locator('.sidebar-settings-btn').click();
    await page.waitForURL('/settings');
    await expect(page.locator('h1:has-text("Settings")')).toBeVisible({ timeout: 10000 });
  });

  test('navigate to Dashboard via title', async ({ page }) => {
    await page.goto('/settings');
    await page.waitForSelector('.sidebar');
    await page.locator('.sidebar-title-link').click();
    await expect(page.locator('h1:has-text("Good")')).toBeVisible({ timeout: 10000 });
  });

  test('navigate to Help', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.sidebar');
    await page.locator('.sidebar-help-icon').click();
    await page.waitForURL('/help');
    await expect(page.locator('h1')).toBeVisible({ timeout: 10000 });
  });
});

test.describe('search overlay', () => {
  test('Cmd+K opens search', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.sidebar');

    await page.keyboard.press('Meta+k');
    await expect(page.locator('.search-overlay')).toBeVisible({ timeout: 5000 });
    // Verify the search input exists and is focused
    await expect(page.locator('.search-overlay input')).toBeVisible();
  });
});

test.describe('keyboard navigation', () => {
  test('g then d goes to dashboard', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.locator('h1:has-text("Settings")')).toBeVisible({ timeout: 10000 });

    await page.keyboard.press('g');
    await page.keyboard.press('d');
    await expect(page.locator('h1:has-text("Good")')).toBeVisible({ timeout: 10000 });
  });

  test('g then n goes to notes', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.locator('h1:has-text("Settings")')).toBeVisible({ timeout: 10000 });

    await page.keyboard.press('g');
    await page.keyboard.press('n');
    await expect(page.locator('h1:has-text("Thoughts")')).toBeVisible({ timeout: 10000 });
  });

  test('g then p goes to people', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.locator('h1:has-text("Settings")')).toBeVisible({ timeout: 10000 });

    await page.keyboard.press('g');
    await page.keyboard.press('p');
    await expect(page.locator('h1:has-text("People")')).toBeVisible({ timeout: 10000 });
  });
});

test.describe('direct page loads', () => {
  // Verify pages work when navigated to directly (not just via sidebar)
  const pages = [
    { path: '/notes', heading: 'Thoughts' },
    { path: '/issues', heading: 'Issues' },
    { path: '/docs', heading: 'Docs' },
    { path: '/people', heading: 'People' },
    { path: '/settings', heading: 'Settings' },
    { path: '/help', heading: '' },
  ];

  for (const { path, heading } of pages) {
    test(`${path} loads directly`, async ({ page }) => {
      await page.goto(path);
      if (heading) {
        await expect(page.locator(`h1:has-text("${heading}")`)).toBeVisible({ timeout: 10000 });
      } else {
        await expect(page.locator('h1')).toBeVisible({ timeout: 10000 });
      }
    });
  }
});
