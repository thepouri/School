import { useMemo } from 'react';

// Dual-thumb range slider (min + max). Supports linear or log scale —
// log is right for heavy-tailed data (members, followers, posts) so the
// useful low range isn't squashed by a few huge outliers.
export default function SliderRange({
  label,
  min = 0,
  max = 1000000,
  step,
  minValue,
  maxValue,
  onMin,
  onMax,
  format,
  scale = 'linear',
  className = '',
}) {
  const from = minValue != null ? Number(minValue) : min;
  const to = maxValue != null ? Number(maxValue) : max;
  const isLog = scale === 'log' && min > 0 && max > min;

  // Format a value for display (e.g. "1.2K").
  const display = useMemo(() => {
    if (format) return format;
    const compact = (n) => {
      if (n >= 1000000) return `${(n / 1000000).toFixed(n % 1000000 ? 1 : 0).replace(/\.0$/, '')}M`;
      if (n >= 1000) return `${(n / 1000).toFixed(n % 1000 ? 1 : 0).replace(/\.0$/, '')}K`;
      return String(Math.round(n));
    };
    return compact;
  }, [format]);

  // Percent position for the track fill.
  const pct = (v) => {
    if (isLog) {
      const lo = Math.max(min, 1);
      const t = Math.log(Math.max(v, lo) / lo) / Math.log(max / lo);
      return Math.min(100, Math.max(0, t * 100));
    }
    return ((v - min) / (max - min)) * 100;
  };

  // Slider position (0-100) → value.
  const toValue = (pos) => {
    const t = pos / 100;
    if (isLog) {
      const lo = Math.max(min, 1);
      return Math.round(lo * Math.pow(max / lo, t));
    }
    const raw = min + t * (max - min);
    return Math.round(raw / (step || 1)) * (step || 1);
  };

  const active = from !== min || to !== max;

  return (
    <div className={`flex min-w-0 flex-col ${className}`}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="min-w-0 truncate px-0.5 text-[11px] font-semibold uppercase tracking-wide text-stone-400">
          {label}
        </span>
        <div className="flex shrink-0 items-center gap-1.5">
          {active && (
            <button
              type="button"
              onClick={() => {
                onMin?.(undefined);
                onMax?.(undefined);
              }}
              className="text-[10px] font-semibold text-brand-600 hover:text-brand-700"
            >
              Clear
            </button>
          )}
          <span className="whitespace-nowrap text-xs font-semibold tabular-nums text-stone-700">
            {active ? `${display(from)} – ${display(to)}` : 'Any'}
          </span>
        </div>
      </div>

      <div className="relative h-5">
        {/* Track */}
        <div className="pointer-events-none absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-stone-200" />
        {/* Active segment */}
        <div
          className="pointer-events-none absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-brand-500"
          style={{
            left: `${pct(from)}%`,
            right: `${100 - pct(to)}%`,
          }}
        />
        {/* Min thumb */}
        <input
          type="range"
          min={0}
          max={100}
          step={isLog ? 1 : undefined}
          value={pct(from)}
          onChange={(e) => {
            const v = toValue(Number(e.target.value));
            if (v <= to) onMin?.(Math.max(v, min));
          }}
          className="dual-range dual-range-min absolute inset-0 h-5 w-full cursor-pointer appearance-none bg-transparent"
          aria-label={`Minimum ${label}`}
        />
        {/* Max thumb */}
        <input
          type="range"
          min={0}
          max={100}
          step={isLog ? 1 : undefined}
          value={pct(to)}
          onChange={(e) => {
            const v = toValue(Number(e.target.value));
            if (v >= from) onMax?.(Math.min(v, max));
          }}
          className="dual-range dual-range-max absolute inset-0 h-5 w-full cursor-pointer appearance-none bg-transparent"
          aria-label={`Maximum ${label}`}
        />
      </div>
    </div>
  );
}
