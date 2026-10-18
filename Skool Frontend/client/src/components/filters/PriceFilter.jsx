import FilterSelect from './FilterSelect.jsx';

// Price filter: single-select bucket (Any / Free / Paid / Free trial / Unknown),
// a Dual-thumb amount slider and an interval select that only appear when
// Paid or Free trial is selected. Bounds come from the DB (meta.priceBounds).

const BUCKET_OPTIONS = [
  { value: 'free', label: 'Free' },
  { value: 'paid', label: 'Paid' },
  { value: 'free-trial', label: 'Free trial' },
];

const INTERVAL_OPTIONS = [
  { value: 'month', label: 'Monthly' },
  { value: 'year', label: 'Yearly' },
  { value: 'one_time', label: 'One-time' },
];

export default function PriceFilter({
  bucketValue,
  onBucket,
  intervalValue,
  onInterval,
  priceFrom,
  priceTo,
  onPriceFrom,
  onPriceTo,
  bounds,
}) {
  const MIN = 0;
  const MAX = bounds?.p99 ?? 10000;
  const active = bucketValue;
  // Slider + interval only for amount-bearing buckets.
  const amountShown = active === 'paid' || active === 'free-trial';

  const from = priceFrom != null ? Number(priceFrom) : MIN;
  const to = priceTo != null ? Number(priceTo) : MAX;

  return (
    <div className="flex flex-col gap-1">
      <FilterSelect
        value={bucketValue}
        onChange={onBucket}
        options={BUCKET_OPTIONS}
        placeholder="Any price"
      />

      {amountShown && (
        <>
          <FilterSelect
            value={intervalValue}
            onChange={onInterval}
            options={INTERVAL_OPTIONS}
            placeholder="Any interval"
          />

          <div className="mt-1 rounded-lg border border-stone-200 bg-stone-50 px-3 py-2">
            <div className="flex items-center justify-between text-xs font-semibold text-stone-500">
              <span>Amount (USD)</span>
              <span className="tabular-nums text-stone-700">
                {from !== MIN || to !== MAX ? `$${from} – $${to}` : 'Any'}
              </span>
            </div>

            <div className="relative mt-1.5">
              <div className="pointer-events-none absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-stone-200" />
              <div
                className="pointer-events-none absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-brand-500"
                style={{
                  left: `${(from / MAX) * 100}%`,
                  right: `${100 - (to / MAX) * 100}%`,
                }}
              />
              <input
                type="range"
                min={MIN}
                max={MAX}
                step={5}
                value={from}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  if (v <= to) onPriceFrom(v);
                }}
                className="dual-range dual-range-min absolute inset-0 h-4 w-full cursor-pointer appearance-none bg-transparent"
                aria-label="Minimum price"
              />
              <input
                type="range"
                min={MIN}
                max={MAX}
                step={5}
                value={to}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  if (v >= from) onPriceTo(v);
                }}
                className="dual-range dual-range-max absolute inset-0 h-4 w-full cursor-pointer appearance-none bg-transparent"
                aria-label="Maximum price"
              />
            </div>

            <div className="mt-1 flex items-center justify-between">
              <span className="text-[11px] text-stone-400">Drag both thumbs to set a range.</span>
              {(from !== MIN || to !== MAX) && (
                <button
                  type="button"
                  onClick={() => {
                    onPriceFrom(undefined);
                    onPriceTo(undefined);
                  }}
                  className="text-[11px] font-semibold text-brand-600 hover:text-brand-700"
                >
                  Clear range
                </button>
              )}
            </div>
          </div>
        </>
      )}

      {!amountShown && (
        <p className="mt-1 text-[11px] text-stone-400">Select “Paid” or “Free trial” to set an amount.</p>
      )}
    </div>
  );
}