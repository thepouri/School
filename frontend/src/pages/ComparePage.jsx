import { useMemo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowLeft, GitCompare } from 'lucide-react';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Cell } from 'recharts';

import { useCompareGroups } from '../api/groups.js';
import { compactNumber, priceLabel, revLabel } from '../lib/format.js';
import { clearCompareIds } from '../lib/compareStore.js';

const PALETTE = ['#4070f4', '#f59e0b', '#10b981', '#8b5cf6', '#ef4444', '#0ea5e9'];

export default function ComparePage() {
  const [searchParams] = useSearchParams();
  const ids = useMemo(
    () => (searchParams.get('ids') || '').split(',').map((s) => s.trim()).filter(Boolean).slice(0, 12),
    [searchParams],
  );
  const { data, isLoading } = useCompareGroups(ids);
  const groups = data || [];

  const metricRows = useMemo(() => {
    if (!groups.length) return [];
    const rows = [
      { key: 'total_members', label: 'Members' },
      { key: 'total_posts', label: 'Posts' },
      {
        key: 'engagement',
        label: 'Posts / 1k members',
        value: (g) =>
          g.total_members > 0 && g.total_posts != null
            ? (Math.round((1000 * g.total_posts) / g.total_members) || '0')
            : '—',
      },
      { key: 'num_courses', label: 'Courses' },
      { key: 'created_at', label: 'Created', type: 'date' },
    ];
    return rows;
  }, [groups]);

  const barData = useMemo(
    () =>
      groups.map((g, i) => ({
        name: g.display_name || g.name,
        members: g.total_members ?? 0,
        revenue: g.estimated_monthly_revenue_usd ?? 0,
        fill: PALETTE[i % PALETTE.length],
      })),
    [groups],
  );

  const cell = (key, g, row) => {
    if (row?.value) return row.value(g);
    if (key === 'created_at') return g.created_at ? new Date(g.created_at).toLocaleDateString('en-US', { year: 'numeric', month: 'short' }) : '—';
    const v = g[key];
    return v == null ? '—' : compactNumber(v);
  };

  if (isLoading) {
    return (
      <div className="mx-auto max-w-5xl pt-6 pb-16">
        <div className="h-8 w-56 animate-pulse rounded bg-stone-200" />
        <div className="mt-6 h-64 animate-pulse rounded-2xl bg-stone-100" />
      </div>
    );
  }

  if (!groups.length) {
    return (
      <div className="mx-auto max-w-5xl py-16 text-center">
        <GitCompare size={40} className="mx-auto text-stone-300" />
        <h1 className="mt-4 text-xl font-bold text-stone-800">Nothing to compare</h1>
        <p className="mt-1 text-sm text-stone-500">Select communities from the browse page and hit Compare.</p>
        <Link to="/" className="mt-6 inline-flex items-center gap-1 text-sm font-semibold text-brand-600 hover:text-brand-700">
          <ArrowLeft size={15} /> Back to browse
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl pt-6 pb-16">
      <Link
        to="/"
        className="mb-4 inline-flex items-center gap-1 text-sm font-medium text-stone-500 transition-colors hover:text-stone-800"
      >
        <ArrowLeft size={15} />
        Back to browse
      </Link>

      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight text-stone-900">Compare communities</h1>
        <button
          type="button"
          onClick={clearCompareIds}
          className="text-sm font-medium text-stone-500 transition-colors hover:text-stone-700"
        >
          Clear selection
        </button>
      </div>

      {/* Metric table */}
      <div className="mt-6 overflow-x-auto rounded-2xl border border-stone-200 bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-stone-200 bg-stone-50 text-left">
              <th className="px-4 py-3 font-semibold text-stone-500">Metric</th>
              {groups.map((g, i) => (
                <th key={g.id} className="px-4 py-3">
                  <Link to={`/groups/${g.id}`} className="font-semibold text-stone-800 hover:text-brand-600">
                    {g.display_name || g.name}
                  </Link>
                  <div className="mt-0.5 text-xs font-normal text-stone-400">
                    {priceLabel(g)?.text || 'Free'}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {metricRows.map((r) => (
              <tr key={r.key} className="border-b border-stone-100 last:border-0">
                <td className="px-4 py-2.5 font-medium text-stone-500">{r.label}</td>
                {groups.map((g) => (
                  <td key={g.id} className="px-4 py-2.5 tabular-nums text-stone-800">
                    {cell(r.key, g, r)}
                  </td>
                ))}
              </tr>
            ))}
            <tr className="bg-emerald-50/40">
              <td className="px-4 py-2.5 font-medium text-emerald-700">Est. revenue</td>
              {groups.map((g) => {
                const r = revLabel(g);
                return (
                  <td key={g.id} className="px-4 py-2.5 font-semibold tabular-nums text-emerald-700">
                    {r ? r.text : '—'}
                  </td>
                );
              })}
            </tr>
          </tbody>
        </table>
      </div>

      {/* Members vs revenue bars */}
      <div className="mt-6 grid grid-cols-1 gap-5 lg:grid-cols-2">
        <div className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
          <h2 className="text-base font-bold text-stone-900">Members</h2>
          <div className="mt-4 h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={barData} margin={{ left: 10, right: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0efee" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#78716c' }} interval={0} />
                <YAxis tick={{ fontSize: 11, fill: '#78716c' }} tickFormatter={compactNumber} />
                <Tooltip formatter={(v) => compactNumber(v)} />
                <Bar dataKey="members" name="Members" radius={[6, 6, 0, 0]}>
                  {barData.map((d, i) => (
                    <Cell key={i} fill={d.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
          <h2 className="text-base font-bold text-stone-900">Est. monthly revenue</h2>
          <div className="mt-4 h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={barData} margin={{ left: 10, right: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0efee" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#78716c' }} interval={0} />
                <YAxis tick={{ fontSize: 11, fill: '#78716c' }} tickFormatter={compactNumber} />
                <Tooltip formatter={(v) => `$${compactNumber(v)}`} />
                <Bar dataKey="revenue" name="Est. revenue/mo" radius={[6, 6, 0, 0]}>
                  {barData.map((d, i) => (
                    <Cell key={i} fill={d.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
}