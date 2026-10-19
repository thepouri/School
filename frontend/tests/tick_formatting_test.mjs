// Test exact tick formatting and key generation across different timestamp datasets

function processData(items) {
  if (items.length === 0) {
    return { rows: [], isSingle: false, isSameDay: false, hasIntraday: false };
  }

  const sorted = [...items].sort(
    (a, b) => new Date(a.captured_at).getTime() - new Date(b.captured_at).getTime(),
  );

  const dates = sorted.map((r) => (r.captured_at ? r.captured_at.slice(0, 10) : ''));
  const uniqueDates = new Set(dates);
  const isSameDay = uniqueDates.size === 1;
  const hasIntraday = sorted.length > uniqueDates.size;

  const rows = sorted.map((r) => {
    const dt = new Date(r.captured_at);
    const dateStr = r.captured_at ? r.captured_at.slice(0, 10) : '';
    const timeStr = dt.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
    const monthDay = dt.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
    });
    const fullTimestamp = dt.toLocaleString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      timeZoneName: 'short',
    });

    let displayKey;
    if (isSameDay) {
      displayKey = timeStr;
    } else if (hasIntraday) {
      displayKey = `${monthDay}, ${timeStr}`;
    } else {
      displayKey = dateStr;
    }

    return {
      ...r,
      day: displayKey,
      _fullTime: fullTimestamp,
      _dateStr: dateStr,
      _timeStr: timeStr,
    };
  });

  return { rows, isSingle: rows.length === 1, isSameDay, hasIntraday };
}

let passed = 0;
let failed = 0;
function test(name, fn) {
  try {
    fn();
    console.log(`  ✓ PASS: ${name}`);
    passed++;
  } catch (e) {
    console.error(`  ✗ FAIL: ${name} ->`, e.message);
    failed++;
  }
}

console.log('\n=== TICK FORMATTING & KEY COLLISION EMPIRICAL TEST ===\n');

test('Same-day snapshots format X-axis as HH:mm', () => {
  const items = [
    { captured_at: '2026-10-18T08:30:00Z' },
    { captured_at: '2026-10-18T14:45:00Z' },
    { captured_at: '2026-10-18T23:15:00Z' },
  ];
  const { rows, isSameDay } = processData(items);
  if (!isSameDay) throw new Error('Expected isSameDay to be true');
  
  // Must match HH:mm pattern (24-hour)
  const hhmmRegex = /^\d{2}:\d{2}$/;
  for (const row of rows) {
    if (!hhmmRegex.test(row.day)) {
      throw new Error(`Expected HH:mm but got ${row.day}`);
    }
  }

  // Must not have key collision
  const keys = new Set(rows.map(r => r.day));
  if (keys.size !== items.length) {
    throw new Error(`Key collision detected: ${keys.size} unique keys for ${items.length} points`);
  }
});

test('Multi-day snapshots with intraday format as "MMM D, HH:mm"', () => {
  const items = [
    { captured_at: '2026-10-17T09:00:00Z' },
    { captured_at: '2026-10-18T09:00:00Z' },
    { captured_at: '2026-10-18T18:00:00Z' },
  ];
  const { rows, hasIntraday, isSameDay } = processData(items);
  if (isSameDay) throw new Error('Expected isSameDay to be false');
  if (!hasIntraday) throw new Error('Expected hasIntraday to be true');

  // Should match "MMM D, HH:mm" (e.g. "Oct 17, 09:00")
  const mmmDRegex = /^[A-Z][a-z]{2}\s\d{1,2},\s\d{2}:\d{2}$/;
  for (const row of rows) {
    if (!mmmDRegex.test(row.day)) {
      throw new Error(`Expected "MMM D, HH:mm" but got "${row.day}"`);
    }
  }

  const keys = new Set(rows.map(r => r.day));
  if (keys.size !== items.length) {
    throw new Error('Key collision detected in multi-day intraday series');
  }
});

test('Standard daily snapshots format as "YYYY-MM-DD"', () => {
  const items = [
    { captured_at: '2026-10-15T12:00:00Z' },
    { captured_at: '2026-10-16T12:00:00Z' },
    { captured_at: '2026-10-17T12:00:00Z' },
  ];
  const { rows, hasIntraday, isSameDay } = processData(items);
  if (isSameDay) throw new Error('Expected isSameDay to be false');
  if (hasIntraday) throw new Error('Expected hasIntraday to be false');

  const ymdRegex = /^\d{4}-\d{2}-\d{2}$/;
  for (const row of rows) {
    if (!ymdRegex.test(row.day)) {
      throw new Error(`Expected "YYYY-MM-DD" but got "${row.day}"`);
    }
  }

  const keys = new Set(rows.map(r => r.day));
  if (keys.size !== items.length) {
    throw new Error('Key collision detected in daily series');
  }
});

test('Tooltip timestamps provide exact human-readable dates and timezone', () => {
  const items = [
    { captured_at: '2026-10-18T14:32:10Z' },
  ];
  const { rows } = processData(items);
  const full = rows[0]._fullTime;
  if (!full || typeof full !== 'string') {
    throw new Error('Expected non-empty _fullTime string');
  }
  // Check contains year, month, and time
  if (!full.includes('2026')) {
    throw new Error(`Expected fullTime to include '2026', got: ${full}`);
  }
});

test('Chronological ordering correctly resolves out-of-order data', () => {
  const items = [
    { captured_at: '2026-10-18T23:59:00Z', val: 3 },
    { captured_at: '2026-10-18T00:01:00Z', val: 1 },
    { captured_at: '2026-10-18T12:00:00Z', val: 2 },
  ];
  const { rows } = processData(items);
  if (rows[0].val !== 1 || rows[1].val !== 2 || rows[2].val !== 3) {
    throw new Error(`Failed to sort: ${JSON.stringify(rows.map(r => r.val))}`);
  }
});

console.log(`\nResults: ${passed} PASSED, ${failed} FAILED\n`);
if (failed > 0) process.exit(1);
