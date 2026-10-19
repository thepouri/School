import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import MetricsChart from '../src/components/MetricsChart.jsx';

// Assert helper
let totalPassed = 0;
let totalFailed = 0;
const results = [];

function assert(condition, testName, details = '') {
  if (condition) {
    totalPassed++;
    results.push({ status: 'PASS', testName, details });
    console.log(`  ✓ PASS: ${testName}`);
  } else {
    totalFailed++;
    results.push({ status: 'FAIL', testName, details });
    console.error(`  ✗ FAIL: ${testName} - ${details}`);
  }
}

function renderChart(kind, id, items, error = null) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  const queryKey = ['metrics', kind, id, {}];
  if (error) {
    queryClient.setQueryData(queryKey, () => {
      throw error;
    });
  } else {
    queryClient.setQueryData(queryKey, { items });
  }

  return renderToStaticMarkup(
    React.createElement(
      QueryClientProvider,
      { client: queryClient },
      React.createElement(MetricsChart, { kind, id })
    )
  );
}

console.log('\n=== EMPIRICAL TEST SUITE: MetricsChart.jsx ===\n');

// -------------------------------------------------------------
// Test Suite 1: Single Snapshot Handling
// -------------------------------------------------------------
console.log('--- Test Suite 1: Single Snapshot Handling ---');

const singleSnapshotGroup = [
  {
    captured_at: '2026-10-18T14:30:00Z',
    total_members: 1250,
    total_posts: 340,
    total_online_members: 42,
    num_courses: 3,
  },
];

const htmlSingleGroup = renderChart('groups', 'single-group-1', singleSnapshotGroup);

assert(
  htmlSingleGroup.includes('Initial Snapshot Captured'),
  'Single group snapshot displays "Initial Snapshot Captured" badge'
);
assert(
  htmlSingleGroup.includes('This community currently has 1 recorded metrics snapshot'),
  'Single group snapshot displays community explanatory message'
);
assert(
  htmlSingleGroup.includes('1.3K') || htmlSingleGroup.includes('1.25K') || htmlSingleGroup.includes('1.2K'),
  'Single group snapshot formats members count with compact notation'
);
assert(
  htmlSingleGroup.includes('Members') &&
  htmlSingleGroup.includes('Posts') &&
  htmlSingleGroup.includes('Online now') &&
  htmlSingleGroup.includes('Courses'),
  'Single group snapshot renders all 4 metric cards (Members, Posts, Online now, Courses)'
);
assert(
  !htmlSingleGroup.includes('recharts-responsive-container') && !htmlSingleGroup.includes('recharts-surface'),
  'Single snapshot does NOT render Recharts chart container or SVG surface'
);
assert(
  !htmlSingleGroup.includes('Same-day snapshots'),
  'Single snapshot does not render same-day header badge'
);

const singleSnapshotUser = [
  {
    captured_at: '2026-10-18T10:15:00Z',
    total_followers: 5400,
    total_contributions: 120,
    owned_groups: 2,
  },
];

const htmlSingleUser = renderChart('users', 'single-user-1', singleSnapshotUser);

assert(
  htmlSingleUser.includes('Initial Snapshot Captured'),
  'Single user snapshot displays "Initial Snapshot Captured" badge'
);
assert(
  htmlSingleUser.includes('This creator currently has 1 recorded metrics snapshot'),
  'Single user snapshot displays creator explanatory message'
);
assert(
  htmlSingleUser.includes('Followers') &&
  htmlSingleUser.includes('Contributions') &&
  htmlSingleUser.includes('Owned groups'),
  'Single user snapshot renders all 3 user metric cards'
);

// -------------------------------------------------------------
// Test Suite 2: Multiple Same-Day Snapshots
// -------------------------------------------------------------
console.log('\n--- Test Suite 2: Multiple Same-Day Snapshots ---');

const sameDaySnapshots = [
  {
    captured_at: '2026-10-18T08:00:00Z',
    total_members: 1000,
    total_posts: 100,
    total_online_members: 10,
    num_courses: 2,
  },
  {
    captured_at: '2026-10-18T13:30:00Z',
    total_members: 1050,
    total_posts: 110,
    total_online_members: 15,
    num_courses: 2,
  },
  {
    captured_at: '2026-10-18T20:15:00Z',
    total_members: 1100,
    total_posts: 125,
    total_online_members: 25,
    num_courses: 3,
  },
];

const htmlSameDay = renderChart('groups', 'same-day-group', sameDaySnapshots);

assert(
  htmlSameDay.includes('Same-day snapshots (2026-10-18)'),
  'Same-day snapshots render header badge with specific date string'
);
assert(
  !htmlSingleGroup.includes('Same-day snapshots (2026-10-18)'),
  'Same-day badge does not appear when single snapshot'
);
assert(
  htmlSameDay.includes('recharts-responsive-container'),
  'Multiple same-day snapshots render Recharts responsive container'
);
assert(
  !htmlSameDay.includes('Initial Snapshot Captured'),
  'Multiple same-day snapshots do NOT render single-snapshot fallback banner'
);

// -------------------------------------------------------------
// Test Suite 3: Mixed Multi-Day Snapshots with Intraday Points
// -------------------------------------------------------------
console.log('\n--- Test Suite 3: Mixed Multi-Day Snapshots with Intraday Points ---');

const mixedMultiDaySnapshots = [
  {
    captured_at: '2026-10-17T09:00:00Z',
    total_members: 900,
    total_posts: 80,
    total_online_members: 5,
    num_courses: 1,
  },
  {
    captured_at: '2026-10-18T10:00:00Z',
    total_members: 1000,
    total_posts: 95,
    total_online_members: 12,
    num_courses: 2,
  },
  {
    captured_at: '2026-10-18T16:45:00Z',
    total_members: 1030,
    total_posts: 105,
    total_online_members: 18,
    num_courses: 2,
  },
];

const htmlMixed = renderChart('groups', 'mixed-day-group', mixedMultiDaySnapshots);

assert(
  !htmlMixed.includes('Same-day snapshots'),
  'Mixed multi-day snapshots do NOT display same-day badge'
);
assert(
  htmlMixed.includes('recharts-responsive-container'),
  'Mixed multi-day snapshots render Recharts responsive container'
);
assert(
  !htmlMixed.includes('Initial Snapshot Captured'),
  'Mixed multi-day snapshots do not render initial snapshot card'
);

// -------------------------------------------------------------
// Test Suite 4: Standard Multi-Day Snapshots
// -------------------------------------------------------------
console.log('\n--- Test Suite 4: Standard Multi-Day Snapshots ---');

const standardDailySnapshots = [
  {
    captured_at: '2026-10-15T00:00:00Z',
    total_members: 800,
    total_posts: 70,
    total_online_members: 5,
    num_courses: 1,
  },
  {
    captured_at: '2026-10-16T00:00:00Z',
    total_members: 850,
    total_posts: 75,
    total_online_members: 8,
    num_courses: 1,
  },
  {
    captured_at: '2026-10-17T00:00:00Z',
    total_members: 900,
    total_posts: 80,
    total_online_members: 10,
    num_courses: 1,
  },
];

const htmlDaily = renderChart('groups', 'daily-group', standardDailySnapshots);

assert(
  !htmlDaily.includes('Same-day snapshots'),
  'Standard daily snapshots do NOT display same-day badge'
);
assert(
  htmlDaily.includes('recharts-responsive-container'),
  'Standard daily snapshots render Recharts responsive container'
);

// -------------------------------------------------------------
// Test Suite 5: Empty Dataset Graceful Fallback
// -------------------------------------------------------------
console.log('\n--- Test Suite 5: Empty Dataset Graceful Fallback ---');

const htmlEmpty = renderChart('groups', 'empty-group', []);

assert(
  htmlEmpty.includes('No snapshots in this range yet.'),
  'Empty dataset displays "No snapshots in this range yet." fallback'
);
assert(
  !htmlEmpty.includes('recharts-responsive-container'),
  'Empty dataset does not render Recharts responsive container'
);
assert(
  !htmlEmpty.includes('Initial Snapshot Captured'),
  'Empty dataset does not render Initial Snapshot banner'
);

// -------------------------------------------------------------
// Test Suite 6: Stress & Adversarial Data Processing
// -------------------------------------------------------------
console.log('\n--- Test Suite 6: Stress & Adversarial Edge Cases ---');

// Unordered / reverse timestamps
const reversedSnapshots = [
  { captured_at: '2026-10-18T22:00:00Z', total_members: 500 },
  { captured_at: '2026-10-18T05:00:00Z', total_members: 450 },
  { captured_at: '2026-10-18T12:00:00Z', total_members: 480 },
];
const htmlReversed = renderChart('groups', 'rev-group', reversedSnapshots);
assert(
  htmlReversed.includes('Same-day snapshots (2026-10-18)'),
  'Unsorted snapshots correctly group into same-day and sort chronologically'
);

// Null / undefined metrics in single snapshot
const nullFieldsSnapshot = [
  {
    captured_at: '2026-10-18T12:00:00Z',
    total_members: null,
    total_posts: undefined,
    total_online_members: 0,
    num_courses: null,
  },
];
const htmlNullFields = renderChart('groups', 'null-group', nullFieldsSnapshot);
assert(
  htmlNullFields.includes('—'),
  'Null/undefined metrics render "—" placeholder gracefully'
);
assert(
  htmlNullFields.includes('0'),
  'Zero value renders "0" rather than "—" or NaN'
);

// Extreme magnitude numbers
const extremeSnapshot = [
  {
    captured_at: '2026-10-18T12:00:00Z',
    total_members: 4500000,
    total_posts: 120000,
    total_online_members: 999,
    num_courses: 0,
  },
];
const htmlExtreme = renderChart('groups', 'extreme-group', extremeSnapshot);
assert(
  htmlExtreme.includes('4.5M'),
  'Large numbers formatted with "M" suffix (4.5M)'
);
assert(
  htmlExtreme.includes('120K'),
  'Thousands formatted with "K" suffix (120K)'
);

console.log(`\n=== SUMMARY: ${totalPassed} PASSED, ${totalFailed} FAILED ===\n`);

if (totalFailed > 0) {
  process.exit(1);
} else {
  process.exit(0);
}
