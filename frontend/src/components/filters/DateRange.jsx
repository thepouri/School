// Two date inputs (from/to) + quick presets. Values are 'YYYY-MM-DD'.
// onPreset receives an atomic { createdFrom, createdTo } patch so both keys are
// written in a single URL update.
export default function DateRange({ from, to, onFrom, onTo, onPreset }) {
  const inputCls =
    'h-9 w-full rounded-lg border border-stone-200 bg-white px-2.5 text-sm font-medium text-stone-800 outline-none transition-colors hover:border-stone-300 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20';

  const iso = (d) => d.toISOString().slice(0, 10);
  const presets = [
    {
      label: 'Last 30 days',
      patch: () => {
        const t = new Date();
        const f = new Date();
        f.setDate(f.getDate() - 30);
        return { createdFrom: iso(f), createdTo: iso(t) };
      },
    },
    {
      label: 'Last 90 days',
      patch: () => {
        const t = new Date();
        const f = new Date();
        f.setDate(f.getDate() - 90);
        return { createdFrom: iso(f), createdTo: iso(t) };
      },
    },
    {
      label: 'This year',
      patch: () => {
        const t = new Date();
        return { createdFrom: `${t.getFullYear()}-01-01`, createdTo: iso(t) };
      },
    },
  ];

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5">
        <input type="date" className={inputCls} value={from || ''} onChange={(e) => onFrom(e.target.value || undefined)} aria-label="Created from" />
        <span className="text-stone-400">–</span>
        <input type="date" className={inputCls} value={to || ''} onChange={(e) => onTo(e.target.value || undefined)} aria-label="Created to" />
      </div>
      <div className="flex flex-wrap gap-1.5">
        {presets.map((p) => (
          <button
            key={p.label}
            type="button"
            onClick={() => onPreset?.(p.patch())}
            className="rounded-full border border-stone-200 bg-stone-50 px-2.5 py-1 text-xs font-semibold text-stone-600 transition-colors hover:border-brand-300 hover:text-brand-700"
          >
            {p.label}
          </button>
        ))}
        {(from || to) && (
          <button
            type="button"
            onClick={() => onPreset?.({ createdFrom: undefined, createdTo: undefined })}
            className="rounded-full border border-stone-200 px-2.5 py-1 text-xs font-medium text-stone-400 hover:text-stone-600"
          >
            Clear
          </button>
        )}
      </div>
    </div>
  );
}
