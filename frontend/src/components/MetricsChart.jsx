import { useMemo, useState } from 'react';
import { TrendingUp } from 'lucide-react';
import {
  ResponsiveContainer, ComposedChart, Bar, Line, LineChart,
  XAxis, YAxis, Tooltip, CartesianGrid, Legend,
} from 'recharts';
import { useMetrics } from '../api/authApi.js';

const axisTick = { fontSize: 11, fill: '#78716c' };
const tooltipStyle = {
  borderRadius: 10, border: '1px solid #e7e5e4', boxShadow: '0 4px 12px rgba(0,0,0,0.08)', fontSize: 12,
};

const RANGES = [
  { key: '30', label: '30d' },
  { key: '90', label: '90d' },
  { key: 'all', label: 'All' },
];

const compact = (n) => {
  if (n == null) return '';
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1).replace(/\.0$/, '')}K`;
  return String(Math.round(n));
};

// Metric definitions per kind. `scale` marks metrics that live on a very
// different magnitude than the others — those get their own right-hand axis
// when combined, and each metric can also be viewed in isolation.
const GROUP_METRICS = [
  { key: 'total_members', label: 'Members', type: 'bar', color: '#4070f4' },
  { key: 'total_posts', label: 'Posts', type: 'line', color: '#f59e0b', secondary: true },
  { key: 'total_online_members', label: 'Online now', type: 'line', color: '#10b981', secondary: true },
  { key: 'num_courses', label: 'Courses', type: 'line', color: '#8b5cf6', secondary: true },
];

const USER_METRICS = [
  { key: 'total_followers', label: 'Followers', type: 'line', color: '#4070f4' },
  { key: 'total_contributions', label: 'Contributions', type: 'line', color: '#10b981' },
  { key: 'owned_groups', label: 'Owned groups', type: 'line', color: '#8b5cf6', secondary: true },
];

// Time-series snapshots for one group/user. kind: 'groups' | 'users'
export default function MetricsChart({ kind, id }) {
  const [range, setRange] = useState('all');
  const [selected, setSelected] = useState(null); // null = combined view

  const params = useMemo(() => {
    if (range === 'all') return {};
    const from = new Date();
    from.setDate(from.getDate() - Number(range));
    return { from: from.toISOString().slice(0, 10) };
  }, [range]);

  const { data, isLoading, error } = useMetrics(kind, id, params);

  const rows = useMemo(
    () => (data?.items || []).map((r) => ({ ...r, day: r.captured_at.slice(0, 10) })),
    [data],
  );

  const allMetrics = kind === 'groups' ? GROUP_METRICS : USER_METRICS;
  // Combined view keeps primary on the left axis and small-magnitude metrics
  // on a second right-hand axis so both stay readable.
  const visible = selected ? allMetrics.filter((m) => m.key === selected) : allMetrics;
  const hasSecondary = !selected && visible.some((m) => m.secondary);

  return (
    <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-base font-bold text-stone-900">
          <TrendingUp size={17} className="text-brand-500" />
          Changes over time
        </h2>
        <div className="flex gap-1.5">
          {RANGES.map((r) => (
            <button
              key={r.key}
              type="button"
              onClick={() => setRange(r.key)}
              className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
                range === r.key
                  ? 'bg-brand-500 text-white shadow-sm'
                  : 'border border-stone-200 bg-white text-stone-600 hover:border-brand-300 hover:text-brand-700'
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </header>

      {/* Per-metric toggle chips */}
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          onClick={() => setSelected(null)}
          className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
            selected === null
              ? 'bg-stone-800 text-white shadow-sm'
              : 'border border-stone-200 bg-white text-stone-600 hover:border-stone-300'
          }`}
        >
          All
        </button>
        {allMetrics.map((m) => (
          <button
            key={m.key}
            type="button"
            onClick={() => setSelected(selected === m.key ? null : m.key)}
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
              selected === m.key
                ? 'text-white shadow-sm'
                : 'border border-stone-200 bg-white text-stone-600 hover:border-stone-300'
            }`}
            style={selected === m.key ? { backgroundColor: m.color } : undefined}
          >
            {!selected && (
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: m.color }} />
            )}
            {m.label}
          </button>
        ))}
      </div>

      <div className="mt-4 h-72">
        {isLoading && <div className="h-full animate-pulse rounded-xl bg-stone-100" />}
        {!isLoading && error && (
          <p className="flex h-full items-center justify-center text-sm text-red-500">{error.message}</p>
        )}
        {!isLoading && !error && rows.length === 0 && (
          <p className="flex h-full items-center justify-center text-sm text-stone-400">
            No snapshots in this range yet.
          </p>
        )}
        {!isLoading && !error && rows.length > 0 && (
          <ResponsiveContainer width="100%" height="100%">
            {visible.some((m) => m.type === 'bar') ? (
              <ComposedChart data={rows} margin={{ left: 5, right: hasSecondary ? 5 : 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0efee" vertical={false} />
                <XAxis dataKey="day" tick={axisTick} />
                <YAxis yAxisId="l" tick={axisTick} tickFormatter={compact} />
                {hasSecondary && (
                  <YAxis yAxisId="r" orientation="right" tick={axisTick} tickFormatter={compact} />
                )}
                <Tooltip contentStyle={tooltipStyle} formatter={(v) => compact(v)} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                {visible.map((m) =>
                  m.type === 'bar' ? (
                    <Bar
                      key={m.key}
                      yAxisId={hasSecondary && m.secondary ? 'r' : 'l'}
                      dataKey={m.key} name={m.label} fill={m.color}
                      radius={[4, 4, 0, 0]} barSize={28}
                    />
                  ) : (
                    <Line
                      key={m.key}
                      yAxisId={hasSecondary && m.secondary ? 'r' : 'l'}
                      type="monotone" dataKey={m.key} name={m.label}
                      stroke={m.color} strokeWidth={2} dot
                    />
                  ),
                )}
              </ComposedChart>
            ) : (
              <LineChart data={rows} margin={{ left: 5, right: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0efee" vertical={false} />
                <XAxis dataKey="day" tick={axisTick} />
                <YAxis yAxisId="l" tick={axisTick} tickFormatter={compact} />
                {hasSecondary && (
                  <YAxis yAxisId="r" orientation="right" tick={axisTick} tickFormatter={compact} />
                )}
                <Tooltip contentStyle={tooltipStyle} formatter={(v) => compact(v)} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                {visible.map((m) => (
                  <Line
                    key={m.key}
                    yAxisId={hasSecondary && m.secondary ? 'r' : 'l'}
                    type="monotone" dataKey={m.key} name={m.label}
                    stroke={m.color} strokeWidth={2} dot
                  />
                ))}
              </LineChart>
            )}
          </ResponsiveContainer>
        )}
      </div>
      <p className="mt-2 text-[11px] text-stone-400">
        Tip: pick a single metric to see it on its own scale.
      </p>
    </section>
  );
}