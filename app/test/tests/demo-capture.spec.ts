/**
 * Automated demo walkthrough — captures screenshots and video of every major feature.
 *
 * Prerequisites:
 *   make demo          # start demo backend + frontend
 *   make demo-capture  # run this test
 *
 * Output:
 *   demo/screenshots/*.png   — ~30 screenshots for README / GitHub page
 *   demo/video/*.webm        — continuous video walkthrough
 */

import { test, expect, type Page, type BrowserContext } from '@playwright/test';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const SCREENSHOT_DIR = path.resolve(__dirname, '../../../demo/screenshots');
const VIDEO_DIR = path.resolve(__dirname, '../../../demo/video');

async function snap(page: Page, name: string) {
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, `${name}.png`),
    fullPage: false,
  });
}

async function pause(page: Page, ms = 1500) {
  await page.waitForTimeout(ms);
}

test.describe.serial('Demo Capture', () => {
  let context: BrowserContext;
  let page: Page;

  test.beforeAll(async ({ browser }) => {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
    fs.mkdirSync(VIDEO_DIR, { recursive: true });

    context = await browser.newContext({
      viewport: { width: 1280, height: 800 },
      recordVideo: { dir: VIDEO_DIR, size: { width: 1280, height: 800 } },
    });
    page = await context.newPage();
  });

  test.afterAll(async () => {
    const videoPath = await page.video()?.path();
    await page.close();
    await context.close();

    if (videoPath) {
      const dest = path.join(VIDEO_DIR, 'demo-walkthrough.webm');
      try { fs.unlinkSync(dest); } catch { /* ignore */ }
      fs.renameSync(videoPath, dest);
    }
  });

  // --- 01: Briefing Page ---
  test('01 - Briefing Page', async () => {
    await page.goto('/');
    await expect(page.locator('.briefing-banner')).toBeVisible({ timeout: 15000 });
    await pause(page, 2000);
    await snap(page, '01-briefing-overview');

    // Scroll to overnight digest
    const overnightHeader = page.locator('text=Overnight');
    if (await overnightHeader.isVisible().catch(() => false)) {
      await overnightHeader.scrollIntoViewIfNeeded();
      await pause(page);
      // Expand if collapsed
      const showBtn = page.locator('button:has-text("Show")').first();
      if (await showBtn.isVisible().catch(() => false)) {
        await showBtn.click();
        await pause(page);
      }
      await snap(page, '01-briefing-overnight');
    }
  });

  // --- 02: Email Page ---
  test('02 - Email Page', async () => {
    await page.goto('/email');
    await page.waitForSelector('.dashboard-item-row', { timeout: 10000 });
    await pause(page);
    await snap(page, '02-email-inbox');
  });

  // --- 03: Slack Page ---
  test('03 - Slack Page', async () => {
    await page.goto('/slack');
    await page.waitForSelector('.dashboard-item-row', { timeout: 10000 });
    await pause(page);
    await snap(page, '03-slack-messages');
  });

  // --- 04: Notes Page ---
  test('04 - Notes Page', async () => {
    await page.goto('/notes');
    await expect(page.locator('.note-input')).toBeVisible({ timeout: 10000 });
    await pause(page);
    await snap(page, '04-notes-overview');

    // Type @mention to show autocomplete
    await page.locator('.note-input').first().fill('@Sar');
    await pause(page, 1200);
    const dropdown = page.locator('.mention-dropdown');
    if (await dropdown.isVisible().catch(() => false)) {
      await snap(page, '04-notes-mention');
    }

    // Clear and show issue creation hint
    await page.locator('.note-input').first().fill('[m] /p2 Fix API timeout on /orders endpoint');
    await pause(page, 1000);
    const hint = page.locator('.note-link-hint');
    if (await hint.first().isVisible().catch(() => false)) {
      await snap(page, '04-notes-issue-hint');
    }
    await page.locator('.note-input').first().fill('');
  });

  // --- 05: Issues Page ---
  test('05 - Issues Page', async () => {
    await page.goto('/issues');
    await page.waitForSelector('.issue-item', { timeout: 10000 });
    await pause(page);
    await snap(page, '05-issues-list');

    // Click first issue to expand
    await page.locator('.issue-item').first().click();
    await pause(page, 1500);
    const detail = page.locator('.issue-detail');
    if (await detail.isVisible().catch(() => false)) {
      await snap(page, '05-issues-detail');
    }
    await page.keyboard.press('Escape');
    await pause(page, 500);
  });

  // --- 06: People Page ---
  test('06 - People Page', async () => {
    await page.goto('/people');
    await page.waitForSelector('.people-table-row', { timeout: 10000 });
    await pause(page);
    await snap(page, '06-people-table');

    // Search
    const searchInput = page.locator('input[placeholder*="Search"]');
    if (await searchInput.isVisible().catch(() => false)) {
      await searchInput.fill('Sarah');
      await pause(page, 1000);
      await snap(page, '06-people-search');
      await searchInput.fill('');
      await pause(page, 500);
    }

    // Switch to tree view
    await page.locator('button:has-text("Tree")').click();
    await pause(page, 1000);
    await snap(page, '06-people-org-tree');

    // Switch back to table for next test
    await page.locator('button:has-text("Table")').click();
    await pause(page, 500);
  });

  // --- 07: Person Detail Page ---
  test('07 - Person Detail', async () => {
    await page.goto('/people');
    await page.waitForSelector('.people-table-row', { timeout: 10000 });

    // Click Sarah Kim
    const sarahLink = page.locator('a:has-text("Sarah Kim")').first();
    if (await sarahLink.isVisible().catch(() => false)) {
      await sarahLink.click();
      await page.waitForURL(/\/people\//, { timeout: 5000 });
      await pause(page, 1500);
      await snap(page, '07-person-detail');
    }
  });

  // --- 08: Meetings Page ---
  test('08 - Meetings Page', async () => {
    await page.goto('/meetings');
    await pause(page, 2000);
    await snap(page, '08-meetings');
  });

  // --- 09: Notion Page ---
  test('09 - Notion Page', async () => {
    await page.goto('/notion');
    await page.waitForSelector('.dashboard-item-row', { timeout: 10000 });
    await pause(page);
    await snap(page, '09-notion-pages');
  });

  // --- 10: Drive Page ---
  test('10 - Drive Page', async () => {
    await page.goto('/drive');
    await page.waitForSelector('.dashboard-item-row', { timeout: 10000 });
    await pause(page);
    await snap(page, '10-drive-files');
  });

  // --- 11: GitHub Page ---
  test('11 - GitHub Page', async () => {
    await page.goto('/github');
    await expect(page.locator('h1:has-text("GitHub")')).toBeVisible({ timeout: 10000 });
    await pause(page, 2000);
    await snap(page, '11-github-prs');

    // Switch to Open PRs tab
    const openTab = page.locator('.github-tab:has-text("Open PRs")');
    if (await openTab.isVisible().catch(() => false)) {
      await openTab.click();
      await pause(page, 1500);
      await snap(page, '11-github-open');
    }
  });

  // --- 12: Ramp Page ---
  test('12 - Ramp Page', async () => {
    await page.goto('/ramp');
    await page.waitForSelector('.dashboard-item-row', { timeout: 10000 });
    await pause(page);
    await snap(page, '12-ramp-expenses');

    // Navigate to bills tab
    const billsLink = page.locator('a:has-text("Bills")');
    if (await billsLink.isVisible().catch(() => false)) {
      await billsLink.click();
      await pause(page, 1500);
      await snap(page, '12-ramp-bills');
    }
  });

  // --- 13: News Page ---
  test('13 - News Page', async () => {
    await page.goto('/news');
    await page.waitForSelector('.dashboard-item-row', { timeout: 10000 });
    await pause(page);
    await snap(page, '13-news-feed');
  });

  // --- 14: Longform / Writing Page ---
  test('14 - Writing Page', async () => {
    await page.goto('/longform');
    await page.waitForSelector('.longform-table-row', { timeout: 10000 });
    await pause(page);
    await snap(page, '14-longform-list');

    // Click first post to open editor
    await page.locator('.longform-table-row').first().click();
    await pause(page, 1500);

    // Try to switch to split view
    const splitBtn = page.locator('button:has-text("Split")');
    if (await splitBtn.isVisible().catch(() => false)) {
      await splitBtn.click();
      await pause(page, 1000);
    }
    await snap(page, '14-longform-editor');
  });

  // --- 15: Claude Page ---
  test('15 - Claude Page', async () => {
    await page.goto('/claude');
    await pause(page, 3000); // Wait for WebSocket demo terminal to render

    // Open history panel
    const toggleBtn = page.locator('.claude-panel-toggle');
    if (await toggleBtn.isVisible().catch(() => false)) {
      await toggleBtn.click();
      await pause(page, 1000);
    }
    await snap(page, '15-claude-terminal');
  });

  // --- 16: Settings Page ---
  test('16 - Settings Page', async () => {
    await page.goto('/settings');
    await page.waitForSelector('.auth-grid', { timeout: 10000 });
    await pause(page);
    await snap(page, '16-settings');
  });

  // --- 17: Command Palette ---
  test('17 - Command Palette', async () => {
    await page.goto('/');
    await expect(page.locator('.briefing-banner')).toBeVisible({ timeout: 10000 });
    await pause(page, 500);

    // Open with Cmd+K
    await page.keyboard.press('Meta+k');
    await expect(page.locator('.search-overlay')).toBeVisible({ timeout: 3000 });
    await pause(page, 800);

    // Type a search
    await page.locator('.search-input').fill('quarterly review');
    await pause(page, 1500);
    await snap(page, '17-command-palette');

    await page.keyboard.press('Escape');
  });
});
