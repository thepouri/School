import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, BarChart3 } from 'lucide-react';
import {
  ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Cell,
  PieChart, Pie, AreaChart, Area, LineChart, Line, ComposedChart,
} from 'recharts';

import { useAnalytics } from '../api/analytics.js';
import { useMeta } from '../api/meta.js';
import { compactNumber } from '../lib/format.js';
import chartCard from './analytics/chartCard.jsx';
import SliderRange from '../components/filters/SliderRange.jsx';
import ChecklistSelect from '../components/filters/ChecklistSelect.jsx';
import DateRange from '../components/filters/DateRange.jsx';
import { facetOptions } from '../components/filters/FilterHelpers.jsx';

const PALETTE = ['#4070f4', '#6d8ff6', '#f59e0b', '#10b981', '#8b5cf6', '#ef4444', '#0ea5e9', '#f97316'];

const axisTick = { fontSize: 11, fill: '#78716c' };
const tooltipStyle = {
  borderRadius: 10,
  border: '1px solid #e7e5e4',
  boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
  fontSize: 12,
};

function Card({ title, subtitle, insight, children }) {
  return chartCard({ title, subtitle, insight, children });
}

function KpiStrip({ data }) {
  const items = [
    { label: 'Communities', value: data?.groups, hint: 'Total groups indexed' },
    { label: 'People', value: data?.users, hint: 'Total users indexed' },
    { label: 'Memberships', value: data?.memberships, hint: 'user↔group links' },
    { label: 'Member slots', value: data?.member_slots, hint: 'Σ total_members' },
  ];
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      {items.map((it) => (
        <div key={it.label} className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
          <div className="text-sm font-medium text-stone-500">{it.label}</div>
          <div className="mt-1 text-3xl font-bold tracking-tight text-stone-900">
            {compactNumber(it.value)}
          </div>
          <div className="mt-0.5 text-xs text-stone-400">{it.hint}</div>
        </div>
      ))}
    </div>
  );
}

const fmt = (v) => compactNumber(v);

export default function AnalyticsPage() {
  // draft = what the user is configuring (updated instantly by sliders/inputs);
  // applied = what actually drives the charts, only after "Apply" is clicked.
  // This guarantees no mid-typing refetch.
  const [draft, setDraft] = useState({});
  const [applied, setApplied] = useState({});
  const { data: meta } = useMeta();
  const { data, isLoading, error } = useAnalytics(applied);

  const cats = facetOptions(meta?.categories || []);
  const patch = (p) => setDraft((prev) => ({ ...prev, ...p }));
  const setNum = (key) => (v) => patch({ [key]: v });
  const apply = () => setApplied((prev) => ({ ...draft }));
  const reset = () => {
    setDraft({});
    setApplied({});
  };
  const dirty = JSON.stringify(draft) !== JSON.stringify(applied);

  const groupSizes = useMemo(() => {
    const labels = { 'under-100': 'Under 100', '100-1k': '100 – 1k', '1k-10k': '1k – 10k', '10k-100k': '10k – 100k', '100k+': '100k+', unknown: 'Unknown' };
    return (data?.groupSizes || []).map((r) => ({ name: labels[r.bucket] || r.bucket, value: r.count }));
  }, [data]);

  const catMembers = useMemo(
    () => (data?.categoryMembers || []).map((r) => ({ name: titleize(r.value), members: Number(r.members) })),
    [data],
  );

  const priceTiers = useMemo(
    () => (data?.priceTiers || []).map((r) => ({ name: titleize(r.tier), value: r.count })),
    [data],
  );

  const engagement = useMemo(
    () => (data?.categoryEngagement || []).map((r) => ({ name: titleize(r.value), per1k: r.posts_per_1k })),
    [data],
  );

  const topCommunities = useMemo(
    () => (data?.topCommunities || []).map((r) => ({ name: r.display_name || r.name, per1k: r.posts_per_1k, members: r.total_members })),
    [data],
  );

  const revenueLeaders = useMemo(
    () => (data?.revenueLeaders || []).map((r) => ({ name: titleize(r.value), revenue: Number(r.revenue_monthly), paidGroups: r.paid_groups })),
    [data],
  );

  const monetization = useMemo(
    () => (data?.monetizationByCategory || []).map((r) => ({ name: titleize(r.value), pct: Number(r.monetized_pct), avgPrice: r.avg_price, total: r.total_groups })),
    [data],
  );

  const ownerBoard = useMemo(
    () => (data?.ownerLeaderboard || []).map((r) => ({ name: r.full_name || `@${r.value}`, reach: Number(r.reach), groups: r.groups })),
    [data],
  );

  const cohortYears = useMemo(
    () => (data?.growthByCohortYear || []).map((r) => ({
      year: String(r.year),
      groups: r.groups,
      median: Math.round(Number(r.median_members)),
      p90: Math.round(Number(r.p90_members)),
    })),
    [data],
  );

  const sweetSpot = useMemo(
    () => (data?.priceSweetSpot || []).map((r) => ({ name: `$${r.bucket}`, count: r.count, members: Number(r.members) })),
    [data],
  );

  const topLocations = useMemo(
    () => (data?.topLocations || []).map((r) => ({ name: titleize(r.value), value: r.count })),
    [data],
  );

  if (isLoading) {
    return (
      <div className="pb-16">
        <div className="animate-pulse space-y-4">
          <div className="h-8 w-48 rounded bg-stone-200" />
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-28 rounded-2xl bg-stone-200" />
            ))}
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-72 rounded-2xl bg-stone-100" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="py-16 text-center">
        <BarChart3 size={40} className="mx-auto text-stone-300" />
        <h1 className="mt-4 text-xl font-bold text-stone-800">Analytics unavailable</h1>
        <p className="mt-1 text-sm text-stone-500">{error?.message}</p>
      </div>
    );
  }

  return (
    <div className="pb-16">
      <div className="py-8">
        <h1 className="text-3xl font-bold tracking-tight text-stone-900">Skool market analytics</h1>
        <p className="mt-1 text-[15px] text-stone-500">
          Understand the Skool ecosystem before you launch — scale, structure, timing, pricing and engagement.
        </p>
      </div>

      {/* Control panel */}
      <div className="mb-6 rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-end gap-4">
          <div className="w-56">
            <SliderRange
              label="Members"
              min={0} max={1000000} step={1000}
              minValue={draft.minMembers}
              maxValue={draft.maxMembers}
              onMin={setNum('minMembers')}
              onMax={setNum('maxMembers')}
            />
          </div>
          <div className="w-56">
            <SliderRange
              label="Posts"
              min={0} max={200000} step={100}
              minValue={draft.minPosts}
              maxValue={draft.maxPosts}
              onMin={setNum('minPosts')}
              onMax={setNum('maxPosts')}
            />
          </div>
          <div className="w-64">
            <ChecklistSelect
              label="Categories"
              value={draft.categories}
              onChange={(v) => patch({ categories: v })}
              options={cats}
              placeholder="All categories"
            />
          </div>
          <div className="w-72">
            <DateRange
              from={draft.createdFrom}
              to={draft.createdTo}
              onFrom={setNum('createdFrom')}
              onTo={setNum('createdTo')}
              onPreset={patch}
            />
          </div>
          <div className="flex items-end gap-2">
            <button
              type="button"
              onClick={apply}
              disabled={!dirty}
              className="inline-flex h-10 items-center gap-1 rounded-lg bg-brand-500 px-4 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-brand-600 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Apply
            </button>
            <button
              type="button"
              onClick={reset}
              className="inline-flex h-10 items-center gap-1 rounded-lg px-3 text-sm font-medium text-stone-500 transition-colors hover:bg-stone-100 hover:text-stone-700"
            >
              Reset
            </button>
          </div>
        </div>
        <p className="mt-2 text-xs text-stone-400">
          Set the scope for the charts below, then hit <b>Apply</b>. Nothing refetches while you type or drag.
        </p>
      </div>

      {isLoading && !data && (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-28 animate-pulse rounded-2xl bg-stone-200" />
          ))}
        </div>
      )}

      <KpiStrip data={data?.kpi} />

      <div className="mt-6 grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card
          title="Community size distribution"
          subtitle="How groups are distributed by member count"
          insight="The long tail dominates — 73% of communities have under 100 members. The 1k–10k band is sparse but reachable: a strong niche community can land there."
        >
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={groupSizes} layout="vertical" margin={{ left: 10, right: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0efee" horizontal={false} />
              <XAxis type="number" tick={axisTick} tickFormatter={fmt} />
              <YAxis type="category" dataKey="name" width={86} tick={axisTick} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => fmt(v)} />
              <Bar dataKey="value" name="Groups" fill="#4070f4" radius={[0, 6, 6, 0]} barSize={22} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card
          title="Categories by total members"
          subtitle="Where the aggregate audience lives"
          insight="Money and hobbies hold the big audiences. Tech is smaller but concentrated — less crowding, focused demand."
        >
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={catMembers} margin={{ left: 10, right: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0efee" vertical={false} />
              <XAxis dataKey="name" tick={axisTick} interval={0} angle={-20} height={50} textAnchor="end" />
              <YAxis tick={axisTick} tickFormatter={fmt} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => fmt(v)} />
              <Bar dataKey="members" name="Total members" radius={[6, 6, 0, 0]} barSize={26}>
                {catMembers.map((_, i) => (
                  <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card
          title="Price model breakdown"
          subtitle="Share of communities by price tier"
          insight="Paid communities now outnumber free ones, but free communities hold 4× the members. Revenue concentrates in a few paid players — the middle is crowded."
        >
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie data={priceTiers} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={55} outerRadius={95} paddingAngle={3}>
                {priceTiers.map((_, i) => (
                  <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
                ))}
              </Pie>
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => fmt(v)} />
            </PieChart>
          </ResponsiveContainer>
        </Card>

        <Card
          title="Content engagement by category"
          subtitle="Posts per 1,000 members (communities >100 members)"
          insight="Health, self-improvement and spirituality post far more per member than tech or money. If your niche is engagement, follow the content leaders — not just the member leaders."
        >
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={engagement} layout="vertical" margin={{ left: 10, right: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0efee" horizontal={false} />
              <XAxis type="number" tick={axisTick} />
              <YAxis type="category" dataKey="name" width={110} tick={axisTick} />
              <Tooltip contentStyle={tooltipStyle} />
              <Bar dataKey="per1k" name="Posts / 1k members" fill="#10b981" radius={[0, 6, 6, 0]} barSize={20} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card
          title="Communities created per month"
          subtitle="24-month trend — when new communities launch"
          insight="There was a massive launch spike in Aug 2025 (8.5k groups) and steady flow since. Timing a launch to a quiet window can earn you attention that a busy window eats."
        >
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={data.groupsMonthly} margin={{ left: 10, right: 20 }}>
              <defs>
                <linearGradient id="gFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#4070f4" stopOpacity={0.25} />
                  <stop offset="100%" stopColor="#4070f4" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0efee" vertical={false} />
              <XAxis dataKey="month" tick={axisTick} interval={3} />
              <YAxis tick={axisTick} tickFormatter={fmt} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => fmt(v)} />
              <Area type="monotone" dataKey="count" name="New groups" stroke="#4070f4" fill="url(#gFill)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </Card>

        <Card
          title="Cohort growth"
          subtitle="Communities launched vs members accumulated, per month"
          insight="The Aug 2025 cohort (8.5k groups) accumulated ~1.5M members — the biggest wave. Recent cohorts are smaller; the window to stand out is opening again."
        >
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={data.cohortGrowth} margin={{ left: 10, right: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0efee" vertical={false} />
              <XAxis dataKey="month" tick={axisTick} interval={3} />
              <YAxis yAxisId="l" tick={axisTick} tickFormatter={fmt} />
              <YAxis yAxisId="r" orientation="right" tick={axisTick} tickFormatter={fmt} />
              <Tooltip contentStyle={tooltipStyle} />
              <Bar yAxisId="r" dataKey="members" name="Members" fill="#f59e0b" opacity={0.6} radius={[4, 4, 0, 0]} />
              <Line yAxisId="l" type="monotone" dataKey="groups" name="Groups" stroke="#4070f4" strokeWidth={2} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </Card>

        <Card
          title="Revenue leaders by category"
          subtitle="Estimated monthly revenue (interval-normalized: yearly /12, weekly ×4.33)"
          insight="Money communities hold ~$330M/mo of estimated revenue — 2× hobbies. If you sell growth services, these are the niches with budgets."
        >
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={revenueLeaders} layout="vertical" margin={{ left: 10, right: 24 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0efee" horizontal={false} />
              <XAxis type="number" tick={axisTick} tickFormatter={(v) => `$${fmt(v)}`} />
              <YAxis type="category" dataKey="name" width={110} tick={{ ...axisTick, fontSize: 10 }} />
              <Tooltip
                contentStyle={tooltipStyle}
                formatter={(v, n) => (n === 'Est. revenue/mo' ? `$${fmt(v)}` : fmt(v))}
              />
              <Bar dataKey="revenue" name="Est. revenue/mo" fill="#10b981" radius={[0, 6, 6, 0]} barSize={18} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card
          title="Monetization rate by category"
          subtitle="% of communities that are paid or free-trial (min 20 groups)"
          insight="Health and spirituality monetize best (~38% paid at ~$430 avg). High monetization = owners already invest in growth — easier pitch."
        >
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={monetization} layout="vertical" margin={{ left: 10, right: 24 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0efee" horizontal={false} />
              <XAxis type="number" tick={axisTick} unit="%" />
              <YAxis type="category" dataKey="name" width={110} tick={{ ...axisTick, fontSize: 10 }} />
              <Tooltip
                contentStyle={tooltipStyle}
                formatter={(v, n) => (n === 'Paid share' ? `${v}%` : n === 'Avg price' ? `$${v}` : v)}
              />
              <Bar dataKey="pct" name="Paid share" fill="#f59e0b" radius={[0, 6, 6, 0]} barSize={18} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card
          title="Serial owners leaderboard"
          subtitle="Operators running 3+ communities, ranked by total reach"
          insight="Proven multi-community operators are your best partnership targets — they already run Skool as a business and buy help."
        >
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={ownerBoard} layout="vertical" margin={{ left: 10, right: 24 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0efee" horizontal={false} />
              <XAxis type="number" tick={axisTick} tickFormatter={fmt} />
              <YAxis type="category" dataKey="name" width={130} tick={{ ...axisTick, fontSize: 10 }} />
              <Tooltip
                contentStyle={tooltipStyle}
                formatter={(v, n) => (n === 'Reach' ? fmt(v) : v)}
              />
              <Bar dataKey="reach" name="Reach" fill="#8b5cf6" radius={[0, 6, 6, 0]} barSize={16} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card
          title="Cohort scale by launch year"
          subtitle="Median & top-10% community size per creation year"
          insight="Newer cohorts are smaller (2025 median: 25 members vs 115 in 2022–23) — the market is young. Partnering early with rising owners beats chasing legacy giants."
        >
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={cohortYears} margin={{ left: 10, right: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0efee" vertical={false} />
              <XAxis dataKey="year" tick={axisTick} />
              <YAxis yAxisId="l" tick={axisTick} tickFormatter={fmt} />
              <YAxis yAxisId="r" orientation="right" tick={axisTick} tickFormatter={fmt} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => fmt(v)} />
              <Bar yAxisId="l" dataKey="groups" name="Groups launched" fill="#4070f4" opacity={0.35} radius={[4, 4, 0, 0]} />
              <Line yAxisId="r" type="monotone" dataKey="median" name="Median members" stroke="#ef4444" strokeWidth={2} dot />
              <Line yAxisId="r" type="monotone" dataKey="p90" name="P90 members" stroke="#10b981" strokeWidth={2} dot />
            </ComposedChart>
          </ResponsiveContainer>
        </Card>

        <Card
          title="Price sweet spot"
          subtitle="Communities & members per price band (paid groups)"
          insight="$25–50 carries the most members (1.16M) — the volume sweet spot. Above $200 the audience thins fast; premium only works with proven outcomes."
        >
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={sweetSpot} margin={{ left: 10, right: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0efee" vertical={false} />
              <XAxis dataKey="name" tick={axisTick} />
              <YAxis yAxisId="l" tick={axisTick} tickFormatter={fmt} />
              <YAxis yAxisId="r" orientation="right" tick={axisTick} tickFormatter={fmt} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => fmt(v)} />
              <Bar yAxisId="l" dataKey="count" name="Communities" fill="#0ea5e9" radius={[4, 4, 0, 0]} barSize={26} />
              <Line yAxisId="r" type="monotone" dataKey="members" name="Members" stroke="#f59e0b" strokeWidth={2} dot />
            </ComposedChart>
          </ResponsiveContainer>
        </Card>

        <Card
          title="Top locations"
          subtitle="Where people are based (top 10)"
          insight="US cities + UK dominate. A non-US, non-UK positioning is largely uncontested at scale."
        >
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={topLocations} layout="vertical" margin={{ left: 10, right: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0efee" horizontal={false} />
              <XAxis type="number" tick={axisTick} tickFormatter={fmt} />
              <YAxis type="category" dataKey="name" width={130} tick={axisTick} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => fmt(v)} />
              <Bar dataKey="value" name="People" fill="#6d8ff6" radius={[0, 6, 6, 0]} barSize={18} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card
          title="Category × language"
          subtitle="Top 6 languages per category — where non-English demand clusters"
          insight="Spanish money communities number in the thousands — a non-English niche with real scale and fewer English competitors."
        >
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <tbody>
                {data.catLangHeat.map((r, i) => (
                  <tr key={i} className="border-b border-stone-100 last:border-0">
                    <td className="py-1.5 pr-2 font-medium text-stone-700">{titleize(r.value)}</td>
                    <td className="py-1.5 pr-2 text-stone-500">{titleize(r.lang)}</td>
                    <td className="py-1.5 text-right tabular-nums text-stone-700">{r.count.toLocaleString('en-US')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <div className="mt-8">
        <Link
          to="/"
          className="inline-flex items-center gap-1 text-sm font-medium text-stone-500 transition-colors hover:text-stone-800"
        >
          <ArrowLeft size={15} />
          Back to browsing
        </Link>
      </div>
    </div>
  );
}

function titleize(s = '') {
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}