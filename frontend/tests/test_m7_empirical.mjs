import { createServer } from 'http';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { chromium } from 'playwright-core';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const distDir = path.resolve(__dirname, '../dist');

// MIME types dictionary
const MIME_TYPES = {
  '.html': 'text/html',
  '.js': 'application/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
};

// Create a static HTTP server with SPA fallback
function startServer(port = 4173) {
  return new Promise((resolve, reject) => {
    const server = createServer((req, res) => {
      let reqPath = req.url.split('?')[0];
      let filePath = path.join(distDir, reqPath === '/' ? 'index.html' : reqPath);

      if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
        filePath = path.join(distDir, 'index.html');
      }

      fs.readFile(filePath, (err, content) => {
        if (err) {
          res.writeHead(500);
          res.end('Server Error: ' + err.code);
          return;
        }
        const ext = path.extname(filePath).toLowerCase();
        const contentType = MIME_TYPES[ext] || 'application/octet-stream';
        res.writeHead(200, { 'Content-Type': contentType });
        res.end(content, 'utf-8');
      });
    });

    server.listen(port, () => {
      console.log(`[Server] Static SPA server listening on http://localhost:${port}`);
      resolve(server);
    });
    server.on('error', reject);
  });
}

// Generate valid admin auth payload in localStorage
const FUTURE_EXP = Math.floor(Date.now() / 1000) + 3600 * 24 * 30; // 30 days
const MOCK_JWT_PAYLOAD = Buffer.from(JSON.stringify({ sub: 1, exp: FUTURE_EXP })).toString('base64');
const MOCK_TOKEN = `header.${MOCK_JWT_PAYLOAD}.signature`;
const MOCK_ACCOUNT = JSON.stringify({ id: 1, email: 'admin@skool.local', is_admin: true });

async function runEmpiricalSuite() {
  const PORT = 4173;
  const server = await startServer(PORT);
  const results = [];

  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true,
  });

  try {
    const context = await browser.newContext();

    // Helper to setup admin session
    async function initPage(context) {
      const page = await context.newPage();
      await page.addInitScript(({ token, account }) => {
        localStorage.setItem('skool_token', token);
        localStorage.setItem('skool_account', account);
      }, { token: MOCK_TOKEN, account: MOCK_ACCOUNT });
      return page;
    }

    // Default mock data
    const mockStatusHealthy = {
      daemon: {
        status: 'RUNNING',
        last_heartbeat: new Date().toISOString(),
        is_paused: false,
      },
      schedules: {
        refresh: {
          interval_days: 3,
          cron: '0 2 */3 * *',
          last_run: new Date(Date.now() - 3600000 * 12).toISOString(),
          next_run: new Date(Date.now() + 3600000 * 60).toISOString(),
        },
        discovery: {
          interval_days: 7,
          cron: '0 3 * * 0',
          last_run: new Date(Date.now() - 3600000 * 48).toISOString(),
          next_run: new Date(Date.now() + 3600000 * 120).toISOString(),
        },
      },
      stats: {
        total_groups: 42150,
        pending_details: 14,
        pending_owners: 6,
      },
      active_job: null,
    };

    const mockLogs = {
      items: [
        {
          id: 101,
          job_type: 'refresh',
          trigger_type: 'manual',
          status: 'SUCCESS',
          started_at: new Date(Date.now() - 600000).toISOString(),
          finished_at: new Date(Date.now() - 580000).toISOString(),
          exit_code: 0,
          error_message: null,
          lines: [
            { id: 1, created_at: new Date(Date.now() - 600000).toISOString(), level: 'INFO', message: 'Starting refresh cycle' },
            { id: 2, created_at: new Date(Date.now() - 590000).toISOString(), level: 'INFO', message: 'Scanned 120 groups, refreshed 15' },
            { id: 3, created_at: new Date(Date.now() - 580000).toISOString(), level: 'INFO', message: 'Refresh finished cleanly' },
          ],
        },
        {
          id: 102,
          job_type: 'discovery',
          trigger_type: 'scheduled',
          status: 'FAILED',
          started_at: new Date(Date.now() - 1200000).toISOString(),
          finished_at: new Date(Date.now() - 1195000).toISOString(),
          exit_code: 1,
          error_message: 'ProxyPoolTimeout: All upstream proxies exhausted after 5 retries',
          lines: [
            { id: 4, created_at: new Date(Date.now() - 1200000).toISOString(), level: 'INFO', message: 'Initializing crawler with proxy pool' },
            { id: 5, created_at: new Date(Date.now() - 1197000).toISOString(), level: 'WARNING', message: 'Proxy timeout on node 4' },
            { id: 6, created_at: new Date(Date.now() - 1195000).toISOString(), level: 'ERROR', message: 'ProxyPoolTimeout: All upstream proxies exhausted' },
          ],
        },
      ],
    };

    const mockSettings = {
      refresh_interval_days: 3,
      discovery_interval_days: 7,
      is_paused: false,
    };

    // ==========================================
    // TEST 1: Healthy Scraper Dashboard Render
    // ==========================================
    console.log('\n--- Running Test 1: Healthy Dashboard Render ---');
    {
      const page = await initPage(context);
      await page.route('**/api/admin/scraper/status', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockStatusHealthy) }));
      await page.route('**/api/admin/scraper/logs*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockLogs) }));
      await page.route('**/api/admin/scraper/settings', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSettings) }));
      await page.route('**/api/admin/accounts*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }));

      await page.goto(`http://localhost:${PORT}/admin?tab=scraper`, { waitUntil: 'networkidle' });

      // Verify status cards text
      const bodyText = await page.innerText('body');
      const hasRunning = bodyText.includes('RUNNING');
      const hasGroups = bodyText.includes('42,150');
      const hasPendingDetails = bodyText.includes('14');
      const hasPendingOwners = bodyText.includes('6');

      console.log('Daemon RUNNING:', hasRunning);
      console.log('Total groups 42,150:', hasGroups);
      console.log('Pending details 14:', hasPendingDetails);
      console.log('Pending owners 6:', hasPendingOwners);

      results.push({
        test: 'Healthy Dashboard Render',
        pass: hasRunning && hasGroups && hasPendingDetails && hasPendingOwners,
        details: `RUNNING=${hasRunning}, groups=${hasGroups}, pending=${hasPendingDetails}`,
      });
      await page.close();
    }

    // ==========================================
    // TEST 2: Error Resilience on API 500
    // ==========================================
    console.log('\n--- Running Test 2: Error Resilience on API 500 ---');
    {
      const page = await initPage(context);
      let pageErrorThrown = false;
      page.on('pageerror', (err) => {
        console.error('[PageError Caught]:', err.message);
        pageErrorThrown = true;
      });

      // API 500 for status
      await page.route('**/api/admin/scraper/status', (route) => route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Database connection failed: pool timeout (500)' }),
      }));
      await page.route('**/api/admin/scraper/logs*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockLogs) }));
      await page.route('**/api/admin/scraper/settings', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSettings) }));
      await page.route('**/api/admin/accounts*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }));

      await page.goto(`http://localhost:${PORT}/admin?tab=scraper`, { waitUntil: 'networkidle' });
      await page.waitForTimeout(1000);

      const bodyText = await page.innerText('body');
      const pageCrashed = pageErrorThrown || bodyText.length < 50;

      // Check if error alert banner is displayed
      const errorBannerVisible = bodyText.includes('Database connection failed') || bodyText.includes('Request failed (500)');
      // Check how status cards render
      const hasStopped = bodyText.includes('STOPPED');
      const hasZeroGroups = bodyText.includes('0');

      console.log('Page crashed:', pageCrashed);
      console.log('Error alert banner rendered for status error:', errorBannerVisible);
      console.log('Cards show fallback STOPPED:', hasStopped);
      console.log('Cards show fallback 0 groups:', hasZeroGroups);

      results.push({
        test: 'Status API 500 Resilience (No Crash)',
        pass: !pageCrashed,
        details: `pageCrashed=${pageCrashed}`,
      });

      results.push({
        test: 'Status API 500 Error Banner Display',
        pass: errorBannerVisible,
        details: `errorBannerVisible=${errorBannerVisible}`,
      });
      await page.close();
    }

    // ==========================================
    // TEST 3: Error Resilience on Network Error
    // ==========================================
    console.log('\n--- Running Test 3: Error Resilience on Network Error ---');
    {
      const page = await initPage(context);
      let pageErrorThrown = false;
      page.on('pageerror', (err) => {
        console.error('[PageError Caught]:', err.message);
        pageErrorThrown = true;
      });

      // Network abort for status
      await page.route('**/api/admin/scraper/status', (route) => route.abort('failed'));
      await page.route('**/api/admin/scraper/logs*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockLogs) }));
      await page.route('**/api/admin/scraper/settings', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSettings) }));
      await page.route('**/api/admin/accounts*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }));

      await page.goto(`http://localhost:${PORT}/admin?tab=scraper`, { waitUntil: 'networkidle' });
      await page.waitForTimeout(1000);

      const bodyText = await page.innerText('body');
      const pageCrashed = pageErrorThrown || bodyText.length < 50;
      const errorBannerVisible = bodyText.includes('Failed to fetch') || bodyText.includes('NetworkError') || bodyText.includes('error');

      console.log('Network error - page crashed:', pageCrashed);
      console.log('Network error - error banner visible:', errorBannerVisible);

      results.push({
        test: 'Status Network Error Resilience (No Crash)',
        pass: !pageCrashed,
        details: `pageCrashed=${pageCrashed}`,
      });

      results.push({
        test: 'Status Network Error Banner Display',
        pass: errorBannerVisible,
        details: `errorBannerVisible=${errorBannerVisible}`,
      });
      await page.close();
    }

    // ==========================================
    // TEST 4: Modal Console Open / Close & Content
    // ==========================================
    console.log('\n--- Running Test 4: Modal Open / Close & Content ---');
    {
      const page = await initPage(context);
      await page.route('**/api/admin/scraper/status', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockStatusHealthy) }));
      await page.route('**/api/admin/scraper/logs*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockLogs) }));
      await page.route('**/api/admin/scraper/settings', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSettings) }));
      await page.route('**/api/admin/accounts*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }));

      await page.goto(`http://localhost:${PORT}/admin?tab=scraper`, { waitUntil: 'networkidle' });

      // Click "View Output" for failed job #102 (second row)
      const viewButtons = await page.$$('button:has-text("View Output")');
      console.log(`Found ${viewButtons.length} "View Output" buttons.`);

      // Click the second one (Job #102)
      await viewButtons[1].click();
      await page.waitForTimeout(300);

      // Verify modal is visible
      let modalHeader = await page.isVisible('text=Job #102 Output Console');
      let modalError = await page.isVisible('text=ProxyPoolTimeout: All upstream proxies exhausted');
      let terminalLine = await page.isVisible('text=Proxy timeout on node 4');

      console.log('Modal opened for Job #102:', modalHeader);
      console.log('Modal displays error banner:', modalError);
      console.log('Modal displays terminal lines:', terminalLine);

      // Click "Close Console"
      await page.click('button:has-text("Close Console")');
      await page.waitForTimeout(300);

      let modalClosed = !(await page.isVisible('text=Job #102 Output Console'));
      console.log('Modal closed via "Close Console":', modalClosed);

      // Re-open Job #101 (first row) and close via 'X' button
      await viewButtons[0].click();
      await page.waitForTimeout(300);
      let modalHeader101 = await page.isVisible('text=Job #101 Output Console');
      console.log('Modal re-opened for Job #101:', modalHeader101);

      // Click the X button inside modal
      const closeX = await page.$('div[role="dialog"] button:has(svg), .fixed.inset-0 button:has(svg.lucide-x)');
      if (closeX) {
        await closeX.click();
      } else {
        // Fallback selector
        await page.click('.fixed.inset-0 button:has-text("")');
      }
      await page.waitForTimeout(300);
      let modalClosedViaX = !(await page.isVisible('text=Job #101 Output Console'));
      console.log('Modal closed via X button:', modalClosedViaX);

      results.push({
        test: 'Modal Terminal Open/Close & Content Inspection',
        pass: modalHeader && modalError && terminalLine && modalClosed && modalHeader101 && modalClosedViaX,
        details: `modalHeader=${modalHeader}, modalError=${modalError}, closed=${modalClosed}, closedViaX=${modalClosedViaX}`,
      });
      await page.close();
    }

    // ==========================================
    // TEST 5: Schedule Settings Clamping (1 to 3650 days)
    // ==========================================
    console.log('\n--- Running Test 5: Schedule Settings Clamping (1-3650 days) ---');
    {
      const page = await initPage(context);
      let interceptedSettingsPayload = null;

      await page.route('**/api/admin/scraper/status', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockStatusHealthy) }));
      await page.route('**/api/admin/scraper/logs*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockLogs) }));
      await page.route('**/api/admin/scraper/settings', (route) => {
        if (route.request().method() === 'POST') {
          interceptedSettingsPayload = JSON.parse(route.request().postData());
          route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'updated' }) });
        } else {
          route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSettings) });
        }
      });
      await page.route('**/api/admin/accounts*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }));

      await page.goto(`http://localhost:${PORT}/admin?tab=scraper`, { waitUntil: 'networkidle' });

      // Inspect HTML attributes of interval inputs
      const refreshInput = await page.$('label:has-text("Refresh Interval") + p + input, input[min="1"][max="3650"]');
      const minAttr = await refreshInput.getAttribute('min');
      const maxAttr = await refreshInput.getAttribute('max');
      const typeAttr = await refreshInput.getAttribute('type');

      console.log(`Refresh input: type=${typeAttr}, min=${minAttr}, max=${maxAttr}`);

      // Try typing 0 (out of bounds < 1) and submitting
      await refreshInput.fill('0');
      await page.click('button:has-text("Save Schedule Settings")');
      await page.waitForTimeout(300);

      // Check if native validity stopped form submission
      const validityValid0 = await refreshInput.evaluate((el) => el.validity.valid);
      const validityRangeUnderflow = await refreshInput.evaluate((el) => el.validity.rangeUnderflow);
      console.log(`Value "0" validity: valid=${validityValid0}, rangeUnderflow=${validityRangeUnderflow}`);
      console.log('Intercepted payload on 0 submission:', interceptedSettingsPayload);

      const submitted0 = interceptedSettingsPayload !== null;

      // Try typing 5000 (out of bounds > 3650)
      interceptedSettingsPayload = null;
      await refreshInput.fill('5000');
      await page.click('button:has-text("Save Schedule Settings")');
      await page.waitForTimeout(300);

      const validityValid5000 = await refreshInput.evaluate((el) => el.validity.valid);
      const validityRangeOverflow = await refreshInput.evaluate((el) => el.validity.rangeOverflow);
      console.log(`Value "5000" validity: valid=${validityValid5000}, rangeOverflow=${validityRangeOverflow}`);
      console.log('Intercepted payload on 5000 submission:', interceptedSettingsPayload);

      const submitted5000 = interceptedSettingsPayload !== null;

      // Now enter valid value (e.g. 5)
      await refreshInput.fill('5');
      await page.click('button:has-text("Save Schedule Settings")');
      await page.waitForTimeout(500);

      console.log('Intercepted payload on valid "5" submission:', interceptedSettingsPayload);
      const feedbackVisible = await page.isVisible('text=Schedule intervals and parameters updated successfully.');
      console.log('Feedback banner displayed on success:', feedbackVisible);

      results.push({
        test: 'Schedule Settings Input Clamping Attributes',
        pass: minAttr === '1' && maxAttr === '3650' && typeAttr === 'number',
        details: `type=${typeAttr}, min=${minAttr}, max=${maxAttr}`,
      });

      results.push({
        test: 'Schedule Settings Native Form Validation Clamping',
        pass: validityRangeUnderflow && validityRangeOverflow && !submitted0 && !submitted5000 && interceptedSettingsPayload?.refresh_interval_days === 5,
        details: `underflowBlocked=${!submitted0}, overflowBlocked=${!submitted5000}, validSubmitted=${interceptedSettingsPayload?.refresh_interval_days === 5}`,
      });
      await page.close();
    }

    // ==========================================
    // TEST 6: Trigger Execution Action Feedback
    // ==========================================
    console.log('\n--- Running Test 6: Trigger Execution Action Feedback ---');
    {
      const page = await initPage(context);
      let triggerPayload = null;

      await page.route('**/api/admin/scraper/status', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockStatusHealthy) }));
      await page.route('**/api/admin/scraper/logs*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockLogs) }));
      await page.route('**/api/admin/scraper/settings', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSettings) }));
      await page.route('**/api/admin/accounts*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
      await page.route('**/api/admin/scraper/trigger', (route) => {
        triggerPayload = JSON.parse(route.request().postData());
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'queued', job_id: 205, mode: triggerPayload.mode }),
        });
      });

      await page.goto(`http://localhost:${PORT}/admin?tab=scraper`, { waitUntil: 'networkidle' });

      // Click "Trigger Refresh Now"
      await page.click('button:has-text("Trigger Refresh Now")');
      await page.waitForTimeout(500);

      const successBannerVisible = await page.isVisible('text=Scraper job #205 (refresh) queued successfully!');
      console.log('Trigger success banner displayed:', successBannerVisible);

      // Now simulate trigger error
      await page.route('**/api/admin/scraper/trigger', (route) => {
        route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'Harvester daemon process unresponsive' }),
        });
      });

      await page.click('button:has-text("Trigger Deep Discovery")');
      await page.waitForTimeout(500);

      const errorBannerVisible = await page.isVisible('text=Failed to queue all job: Harvester daemon process unresponsive');
      console.log('Trigger error banner displayed on 500:', errorBannerVisible);

      results.push({
        test: 'Manual Trigger Execution & Error Banner',
        pass: successBannerVisible && errorBannerVisible,
        details: `successBanner=${successBannerVisible}, errorBanner=${errorBannerVisible}`,
      });
      await page.close();
    }

    // ==========================================
    // TEST 7: Active Job Banner Representation
    // ==========================================
    console.log('\n--- Running Test 7: Active Job Running Banner ---');
    {
      const page = await initPage(context);
      const mockStatusActive = {
        ...mockStatusHealthy,
        active_job: {
          id: 301,
          job_type: 'discovery',
          status: 'RUNNING',
          started_at: new Date(Date.now() - 45000).toISOString(),
        },
      };

      await page.route('**/api/admin/scraper/status', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockStatusActive) }));
      await page.route('**/api/admin/scraper/logs*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockLogs) }));
      await page.route('**/api/admin/scraper/settings', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSettings) }));
      await page.route('**/api/admin/accounts*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }));

      await page.goto(`http://localhost:${PORT}/admin?tab=scraper`, { waitUntil: 'networkidle' });

      const hasActiveBanner = await page.isVisible('text=Active Scraper Job Running');
      const hasJobNumber = await page.isVisible('text=Job #301');
      const hasExecutingBadge = await page.isVisible('text=Executing');

      // Buttons must be disabled when active job is running
      const refreshDisabled = await page.isDisabled('button:has-text("Trigger Refresh Now")');
      const discoveryDisabled = await page.isDisabled('button:has-text("Trigger Deep Discovery")');

      console.log('Active banner visible:', hasActiveBanner);
      console.log('Job #301 visible:', hasJobNumber);
      console.log('Buttons disabled during active job:', refreshDisabled && discoveryDisabled);

      results.push({
        test: 'Active Job Banner & Button Lockout',
        pass: hasActiveBanner && hasJobNumber && hasExecutingBadge && refreshDisabled && discoveryDisabled,
        details: `banner=${hasActiveBanner}, job=${hasJobNumber}, disabled=${refreshDisabled && discoveryDisabled}`,
      });
      await page.close();
    }

    // ==========================================
    // TEST 8: MetricsChart Single Snapshot & Intraday Formatting
    // ==========================================
    console.log('\n--- Running Test 8: MetricsChart Visualization ---');
    {
      const page = await initPage(context);

      // Single snapshot mock
      const singleSnapshot = {
        items: [
          {
            id: 1,
            group_id: 1,
            captured_at: '2026-10-18T14:30:00Z',
            total_members: 5200,
            total_posts: 180,
            total_online_members: 42,
            num_courses: 5,
          },
        ],
      };

      await page.route('**/api/metrics/groups/1*', (route) => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(singleSnapshot),
      }));
      await page.route('**/api/groups/1', (route) => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 1,
          name: 'AI Automation Guild',
          slug: 'ai-automation',
          description: 'Community for AI builders',
          members_count: 5200,
          created_at: '2026-01-01T00:00:00Z',
        }),
      }));

      await page.goto(`http://localhost:${PORT}/groups/1`, { waitUntil: 'networkidle' });
      await page.waitForTimeout(500);

      const hasSingleBadge = await page.isVisible('text=Initial Snapshot Captured');
      const hasMemberStat = await page.isVisible('text=5.2K');
      const hasOnlineStat = await page.isVisible('text=42');

      console.log('Single snapshot "Initial Snapshot Captured" banner:', hasSingleBadge);
      console.log('Single snapshot stat cards rendered (5.2K, 42):', hasMemberStat && hasOnlineStat);

      results.push({
        test: 'MetricsChart Single Snapshot Clean Rendering',
        pass: hasSingleBadge && hasMemberStat && hasOnlineStat,
        details: `badge=${hasSingleBadge}, members=${hasMemberStat}, online=${hasOnlineStat}`,
      });

      // Intraday same-day mock
      const sameDaySnapshots = {
        items: [
          {
            id: 1,
            group_id: 1,
            captured_at: '2026-10-18T08:00:00Z',
            total_members: 5100,
            total_posts: 175,
            total_online_members: 30,
            num_courses: 5,
          },
          {
            id: 2,
            group_id: 1,
            captured_at: '2026-10-18T14:30:00Z',
            total_members: 5200,
            total_posts: 180,
            total_online_members: 42,
            num_courses: 5,
          },
        ],
      };

      await page.route('**/api/metrics/groups/1*', (route) => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(sameDaySnapshots),
      }));

      // Trigger re-render by changing range or refreshing
      await page.click('button:has-text("30d")');
      await page.waitForTimeout(500);

      const hasSameDayBadge = await page.isVisible('text=Same-day snapshots (2026-10-18)');
      console.log('Same-day snapshots badge visible:', hasSameDayBadge);

      results.push({
        test: 'MetricsChart Same-Day Intraday Handling',
        pass: hasSameDayBadge,
        details: `hasSameDayBadge=${hasSameDayBadge}`,
      });

      await page.close();
    }

  } finally {
    await browser.close();
    server.close();
  }

  console.log('\n======================================================');
  console.log('EMPIRICAL TEST RESULTS SUMMARY');
  console.log('======================================================');
  let allPassed = true;
  for (const r of results) {
    console.log(`[${r.pass ? 'PASS' : 'FAIL'}] ${r.test} - ${r.details}`);
    if (!r.pass) allPassed = false;
  }
  console.log('======================================================');
  console.log(`Final Suite Verdict: ${allPassed ? 'ALL TESTS PASSED' : 'TEST FAILURES DETECTED'}`);
  console.log('======================================================');

  return { allPassed, results };
}

runEmpiricalSuite().then(({ allPassed }) => {
  if (!allPassed) {
    process.exit(1);
  }
}).catch((err) => {
  console.error('Test suite runner crashed:', err);
  process.exit(1);
});
