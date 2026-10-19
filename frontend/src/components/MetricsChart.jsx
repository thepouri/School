import { useMemo, useState } from 'react';
import { TrendingUp, Clock } from 'lucide-react';
import {
  ResponsiveContainer, ComposedChart, Bar, Line, LineChart,
  XAxis, YAxis, Tooltip, CartesianGrid, Legend,
} from 'recharts';
import { useMetrics } from '../api/authApi.js';

const axisTick = { fontSize: 11, fill: '#78716c' };
const tooltipStyle = {
  borderRadius: 10,
  border: '1px solid #e7e5e4',
  boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
  fontSize: 12,
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

// Metric definitions per kind. `secondary` marks metrics that live on a very
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

  const processedData = useMemo(() => {
    const items = data?.items || [];
    if (items.length === 0) {
      return {
        rows: [],
        isSingle: false,
        isSameDay: false,
        hasIntraday: false,
        singleItem: null,
        firstDateStr: null,
      };
    }

    // 1. Sort chronologically ascending
    const sorted = [...items].sort(
      (a, b) => new Date(a.captured_at).getTime() - new Date(b.captured_at).getTime(),
    );

    // 2. Date distribution analysis
    const dates = sorted.map((r) => (r.captured_at ? r.captured_at.slice(0, 10) : ''));
    const uniqueDates = new Set(dates);
    const isSameDay = uniqueDates.size === 1;
    const hasIntraday = sorted.length > uniqueDates.size;

    // 3. Format tick keys and tooltips
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
        // All snapshots share the same calendar date: use "HH:mm"
        displayKey = timeStr;
      } else if (hasIntraday) {
        // Multi-day with multiple intraday points: use "MMM D, HH:mm"
        displayKey = `${monthDay}, ${timeStr}`;
      } else {
        // Standard distinct daily snapshots: use "YYYY-MM-DD"
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

    return {
      rows,
      isSingle: rows.length === 1,
      isSameDay,
      hasIntraday,
      singleItem: rows[0],
      firstDateStr: dates[0],
    };
  }, [data]);

  const { rows, isSingle, isSameDay } = processedData;

  const allMetrics = kind === 'groups' ? GROUP_METRICS : USER_METRICS;
  const visible = selected ? allMetrics.filter((m) => m.key === selected) : allMetrics;
  const hasSecondary = !selected && visible.some((m) => m.secondary);

  return (
    <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2.5">
          <h2 className="flex items-center gap-2 text-base font-bold text-stone-900">
            <TrendingUp size={17} className="text-brand-500" />
            Changes over time
          </h2>
          {isSameDay && rows.length > 1 && (
            <span className="rounded-full border border-brand-200 bg-brand-50 px-2.5 py-0.5 text-xs font-semibold text-brand-700">
              Same-day snapshots ({processedData.firstDateStr})
            </span>
          )}
        </div>
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

      <div className="mt-4">
        {isLoading && (
          <div className="h-72 animate-pulse rounded-xl bg-stone-100" />
        )}
        {!isLoading && error && (
          <p className="flex h-72 items-center justify-center text-sm text-red-500">
            {error.message}
          </p>
        )}
        {!isLoading && !error && rows.length === 0 && (
          <p className="flex h-72 items-center justify-center text-sm text-stone-400">
            No snapshots in this range yet.
          </p>
        )}

        {/* Single-Snapshot Representation */}
        {!isLoading && !error && isSingle && (
          <div className="space-y-4 py-2">
            <div className="flex items-start gap-3 rounded-2xl border border-brand-200 bg-brand-50/70 p-4">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-500 text-white shadow-sm">
                <Clock size={18} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-brand-900">
                    Initial Snapshot Captured
                  </span>
                  <span className="rounded-full bg-brand-200/80 px-2.5 py-0.5 text-xs font-semibold text-brand-900">
                    {processedData.singleItem._fullTime}
                  </span>
                </div>
                <p className="mt-1 text-xs leading-relaxed text-stone-600">
                  This {kind === 'groups' ? 'community' : 'creator'} currently has 1 recorded metrics snapshot. Growth trends and interactive timeline charts will automatically populate as subsequent snapshots are recorded.
                </p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {allMetrics.map((m) => {
                const val = processedData.singleItem[m.key];
                return (
                  <div
                    key={m.key}
                    className="rounded-xl border border-stone-200 bg-stone-50/70 p-3.5"
                  >
                    <div className="flex items-center gap-1.5 text-xs font-medium text-stone-500">
                      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: m.color }} />
                      {m.label}
                    </div>
                    <div className="mt-1 text-xl font-bold tabular-nums text-stone-900">
                      {val != null ? compact(val) : '—'}
                    </div>
                    <div className="text-[11px] text-stone-400">
                      {val != null ? Number(val).toLocaleString('en-US') : ''}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Multi-Point Chart Representation */}
        {!isLoading && !error && rows.length > 1 && (
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              {visible.some((m) => m.type === 'bar') ? (
                <ComposedChart data={rows} margin={{ left: 5, right: hasSecondary ? 5 : 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0efee" vertical={false} />
                  <XAxis dataKey="day" tick={axisTick} minTickGap={20} interval="preserveStartEnd" />
                  <YAxis yAxisId="l" tick={axisTick} tickFormatter={compact} />
                  {hasSecondary && (
                    <YAxis yAxisId="r" orientation="right" tick={axisTick} tickFormatter={compact} />
                  )}
                  <Tooltip
                    contentStyle={tooltipStyle}
                    formatter={(v) => compact(v)}
                    labelFormatter={(label, payload) =>
                      payload?.[0]?.payload?._fullTime || label
                    }
                  />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  {visible.map((m) =>
                    m.type === 'bar' ? (
                      <Bar
                        key={m.key}
                        yAxisId={hasSecondary && m.secondary ? 'r' : 'l'}
                        dataKey={m.key}
                        name={m.label}
                        fill={m.color}
                        radius={[4, 4, 0, 0]}
                        barSize={rows.length > 10 ? undefined : 28}
                      />
                    ) : (
                      <Line
                        key={m.key}
                        yAxisId={hasSecondary && m.secondary ? 'r' : 'l'}
                        type="monotone"
                        dataKey={m.key}
                        name={m.label}
                        stroke={m.color}
                        strokeWidth={2}
                        dot={{ r: 3 }}
                        activeDot={{ r: 5 }}
                      />
                    ),
                  )}
                </ComposedChart>
              ) : (
                <LineChart data={rows} margin={{ left: 5, right: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0efee" vertical={false} />
                  <XAxis dataKey="day" tick={axisTick} minTickGap={20} interval="preserveStartEnd" />
                  <YAxis yAxisId="l" tick={axisTick} tickFormatter={compact} />
                  {hasSecondary && (
                    <YAxis yAxisId="r" orientation="right" tick={axisTick} tickFormatter={compact} />
                  )}
                  <Tooltip
                    contentStyle={tooltipStyle}
                    formatter={(v) => compact(v)}
                    labelFormatter={(label, payload) =>
                      payload?.[0]?.payload?._fullTime || label
                    }
                  />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  {visible.map((m) => (
                    <Line
                      key={m.key}
                      yAxisId={hasSecondary && m.secondary ? 'r' : 'l'}
                      type="monotone"
                      dataKey={m.key}
                      name={m.label}
                      stroke={m.color}
                      strokeWidth={2}
                      dot={{ r: 3 }}
                      activeDot={{ r: 5 }}
                    />
                  ))}
                </LineChart>
              )}
            </ResponsiveContainer>
          </div>
        )}
      </div>
      <p className="mt-2 text-[11px] text-stone-400">
        Tip: pick a single metric to see it on its own scale.
      </p>
    </section>
  );
}