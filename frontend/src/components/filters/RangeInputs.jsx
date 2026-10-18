// Two small numeric inputs for a min/max range on one numeric column.
// Label is optional (defaults off) — FilterBar provides it via <Field>.
export default function RangeInputs({ label, min, max, onMin, onMax, unit = '' }) {
  const inputCls =
    'h-9 w-24 rounded-lg border border-stone-200 bg-white px-2.5 text-sm font-medium text-stone-800 outline-none transition-colors hover:border-stone-300 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20';

  const toNum = (v) => {
    const n = Number.parseInt(v, 10);
    return Number.isFinite(n) && n >= 0 ? n : undefined;
  };

  return (
    <div className="flex flex-col gap-1">
      {label && (
        <span className="px-1 text-[11px] font-semibold uppercase tracking-wide text-stone-400">{label}</span>
      )}
      <div className="flex items-center gap-1.5">
        <input
          type="number"
          min="0"
          value={min ?? ''}
          placeholder="Min"
          onChange={(e) => onMin(toNum(e.target.value))}
          className={inputCls}
        />
        <span className="text-stone-400">–</span>
        <input
          type="number"
          min="0"
          value={max ?? ''}
          placeholder="Max"
          onChange={(e) => onMax(toNum(e.target.value))}
          className={inputCls}
        />
        {unit && <span className="text-xs text-stone-400">{unit}</span>}
      </div>
    </div>
  );
}