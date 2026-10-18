import { BarChart3 } from 'lucide-react';
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts';
import { useMyUsage } from '../api/authApi.js';

const axisTick = { fontSize: 11, fill: '#78716c' };
const tooltipStyle = {
  borderRadius: 10,
  border: '1px solid #e7e5e4',
  boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
  fontSize: 12,
};

export default function UsagePage() {
  const { data, isLoading, error } = useMyUsage();

  return (
    <div className="pb-16">
      <div className="py-8">
        <h1 className="text-3xl font-bold tracking-tight text-stone-900">Your usage</h1>
        <p className="mt-1 text-[15px] text-stone-500">
          API requests over the last {data?.window_days ?? 30} days.
        </p>
      </div>

      {isLoading && (
        <div className="h-28 animate-pulse rounded-2xl bg-stone-200" />
      )}

      {error && (
        <div className="rounded-2xl border border-red-100 bg-red-50 p-6 text-sm text-red-600">
          {error.message}
        </div>
      )}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <div className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
              <div className="text-sm font-medium text-stone-500">Requests</div>
              <div className="mt-1 text-3xl font-bold tracking-tight text-stone-900">
                {(data.total ?? 0).toLocaleString('en-US')}
              </div>
              <div className="mt-0.5 text-xs text-stone-400">last {data.window_days} days</div>
            </div>
            <div className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
              <div className="text-sm font-medium text-stone-500">Active days</div>
              <div className="mt-1 text-3xl font-bold tracking-tight text-stone-900">
                {(data.daily?.length ?? 0).toLocaleString('en-US')}
              </div>
              <div className="mt-0.5 text-xs text-stone-400">days with at least one call</div>
            </div>
            <div className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
              <div className="text-sm font-medium text-stone-500">Daily average</div>
              <div className="mt-1 text-3xl font-bold tracking-tight text-stone-900">
                {Math.round((data.total ?? 0) / (data.window_days || 1)).toLocaleString('en-US')}
              </div>
              <div className="mt-0.5 text-xs text-stone-400">requests / day</div>
            </div>
            <div className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
              <div className="text-sm font-medium text-stone-500">Busiest day</div>
              <div className="mt-1 text-3xl font-bold tracking-tight text-stone-900">
                {Math.max(0, ...(data.daily || []).map((d) => d.requests)).toLocaleString('en-US')}
              </div>
              <div className="mt-0.5 text-xs text-stone-400">peak requests in a day</div>
            </div>
          </div>

          <section className="mt-6 flex flex-col rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
            <header>
              <h2 className="flex items-center gap-2 text-base font-bold text-stone-900">
                <BarChart3 size={17} className="text-brand-500" />
                Daily requests
              </h2>
            </header>
            <div className="mt-4 h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.daily || []} margin={{ left: 10, right: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0efee" vertical={false} />
                  <XAxis dataKey="day" tick={axisTick} tickFormatter={(d) => d.slice(5)} />
                  <YAxis tick={axisTick} allowDecimals={false} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Bar dataKey="requests" name="Requests" fill="#4070f4" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
        </>
      )}
    </div>
  );
}