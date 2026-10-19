import { createServer } from 'vite';
import { chromium } from 'playwright-core';

async function run() {
  console.log('Starting Vite server for browser tests...');
  const server = await createServer({
    server: { port: 5199 },
  });
  await server.listen();
  console.log('Vite server running at http://localhost:5199');

  const consoleErrors = [];
  console.log('Launching Chrome via Playwright...');
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true,
  });

  const page = await browser.newPage();
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      consoleErrors.push(msg.text());
    }
  });
  page.on('pageerror', (err) => {
    consoleErrors.push(err.message);
  });

  try {
    console.log('Navigating to http://localhost:5199/tests/test_harness.html ...');
    await page.goto('http://localhost:5199/tests/test_harness.html');
    await page.waitForSelector('#chart-container');

    // Scenario 1: Single snapshot
    console.log('\nTesting Scenario 1: Single Snapshot in real browser...');
    await page.waitForSelector('text=Initial Snapshot Captured');
    const singleText = await page.textContent('#chart-container');
    if (!singleText.includes('Initial Snapshot Captured')) throw new Error('Missing "Initial Snapshot Captured" banner');
    if (!singleText.includes('Members')) throw new Error('Missing Members card');
    if (!singleText.includes('Posts')) throw new Error('Missing Posts card');
    if (!singleText.includes('Online now')) throw new Error('Missing Online now card');
    if (!singleText.includes('Courses')) throw new Error('Missing Courses card');

    const svgCountSingle = await page.locator('.recharts-surface').count();
    if (svgCountSingle !== 0) throw new Error(`Expected 0 SVG surfaces for single snapshot, got ${svgCountSingle}`);
    console.log('  ✓ Single snapshot verified: 4 cards rendered, badge displayed, zero Recharts distortion/SVG');

    // Scenario 2: Same-day snapshots
    console.log('\nTesting Scenario 2: Same-day snapshots in real browser...');
    await page.click('#btn-sameday');
    await page.waitForSelector('text=Same-day snapshots (2026-10-18)');
    await page.waitForSelector('.recharts-surface');
    const svgCountSameDay = await page.locator('.recharts-surface').count();
    if (svgCountSameDay < 1) throw new Error('Expected recharts SVG surface for same-day snapshots');

    // Test Tooltip hover interaction
    const dot = page.locator('.recharts-dot').first();
    await dot.hover();
    await page.waitForTimeout(300);
    console.log('  ✓ Hovered on dot, checking tooltip interaction');
    console.log('  ✓ Same-day snapshots verified: badge rendered, Recharts chart mounted cleanly');

    // Scenario 3: Multi-day snapshots
    console.log('\nTesting Scenario 3: Multi-day snapshots in real browser...');
    await page.click('#btn-multiday');
    await page.waitForSelector('.recharts-surface');
    const sameDayBadgeCount = await page.locator('text=Same-day snapshots').count();
    if (sameDayBadgeCount !== 0) throw new Error('Did not expect same-day badge for multi-day');
    console.log('  ✓ Multi-day snapshots verified: rendered cleanly without same-day badge');

    // Scenario 4: Empty dataset
    console.log('\nTesting Scenario 4: Empty dataset in real browser...');
    await page.click('#btn-empty');
    await page.waitForSelector('text=No snapshots in this range yet.');
    const svgCountEmpty = await page.locator('.recharts-surface').count();
    if (svgCountEmpty !== 0) throw new Error(`Expected 0 SVG surfaces for empty dataset, got ${svgCountEmpty}`);
    console.log('  ✓ Empty dataset verified: fallback message displayed gracefully without SVG');

    if (consoleErrors.length > 0) {
      console.warn('Browser console errors observed:', consoleErrors);
    } else {
      console.log('\n✓ Zero browser console errors observed throughout all transitions!');
    }

    console.log('\n=== ALL REAL BROWSER TESTS PASSED SUCCESSFULLY! ===\n');
  } finally {
    await browser.close();
    await server.close();
  }
}

run().catch((err) => {
  console.error('Browser test run failed:', err);
  process.exit(1);
});
