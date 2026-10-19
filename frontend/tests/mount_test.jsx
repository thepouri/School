import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import MetricsChart from '../src/components/MetricsChart.jsx';
import '../src/index.css';

const scenarios = {
  single: [
    {
      captured_at: '2026-10-18T14:30:00Z',
      total_members: 1250,
      total_posts: 340,
      total_online_members: 42,
      num_courses: 3,
    },
  ],
  sameday: [
    {
      captured_at: '2026-10-18T08:00:00Z',
      total_members: 1000,
      total_posts: 100,
      total_online_members: 10,
      num_courses: 2,
    },
    {
      captured_at: '2026-10-18T14:00:00Z',
      total_members: 1050,
      total_posts: 110,
      total_online_members: 15,
      num_courses: 2,
    },
  ],
  multiday: [
    {
      captured_at: '2026-10-16T12:00:00Z',
      total_members: 800,
      total_posts: 70,
      total_online_members: 5,
      num_courses: 1,
    },
    {
      captured_at: '2026-10-17T12:00:00Z',
      total_members: 850,
      total_posts: 75,
      total_online_members: 8,
      num_courses: 1,
    },
    {
      captured_at: '2026-10-18T12:00:00Z',
      total_members: 900,
      total_posts: 80,
      total_online_members: 10,
      num_courses: 1,
    },
  ],
  empty: [],
};

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
    },
  },
});

// Seed data
Object.entries(scenarios).forEach(([key, items]) => {
  queryClient.setQueryData(['metrics', 'groups', key, {}], { items });
});

function App() {
  const [activeScenario, setActiveScenario] = useState('single');

  return (
    <QueryClientProvider client={queryClient}>
      <div className="max-w-4xl mx-auto space-y-4">
        <div className="flex gap-2">
          {Object.keys(scenarios).map((s) => (
            <button
              key={s}
              id={`btn-${s}`}
              onClick={() => setActiveScenario(s)}
              className="px-3 py-1 bg-stone-200 rounded font-semibold text-xs"
            >
              {s}
            </button>
          ))}
        </div>
        <div id="chart-container">
          <MetricsChart kind="groups" id={activeScenario} />
        </div>
      </div>
    </QueryClientProvider>
  );
}

const root = createRoot(document.getElementById('test-root'));
root.render(<App />);
