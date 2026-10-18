import FilterSelect from './FilterSelect.jsx';

// Helper to build labeled options from a raw facet list (value + count)
export function facetOptions(facets) {
  return (facets || []).map((f) => ({
    value: f.value,
    label: f.value === 'unknown' ? 'Unknown' : titleize(f.value),
    count: f.count,
  }));
}

export function titleize(s = '') {
  return s
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// Boolean toggle select rendering "Any / Yes / No".
// "Any" is always selectable — picking it clears the filter (undefined).
export function BoolSelect({ label, value, onChange, yesText = 'Yes', noText = 'No' }) {
  const shown = value === undefined ? 'any' : value ? 'yes' : 'no';
  return (
    <label className="flex min-w-[140px] flex-col gap-1">
      <span className="px-1 text-[11px] font-semibold uppercase tracking-wide text-stone-400">{label}</span>
      <div className="relative">
        <select
          value={shown}
          onChange={(e) => {
            const v = e.target.value;
            onChange(v === 'any' ? undefined : v === 'yes');
          }}
          className="h-9 w-full cursor-pointer appearance-none rounded-lg border border-stone-200 bg-white px-3 pr-8 text-sm font-medium text-stone-800 outline-none transition-colors hover:border-stone-300 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20"
        >
          <option value="any">Any</option>
          <option value="yes">{yesText}</option>
          <option value="no">{noText}</option>
        </select>
        <svg
          className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-stone-400"
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </div>
    </label>
  );
}