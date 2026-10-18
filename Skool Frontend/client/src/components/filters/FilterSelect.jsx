import { ChevronDown } from 'lucide-react';

// Labeled select with count-rich options
export default function FilterSelect({ label, value, onChange, options, placeholder = 'Any' }) {
  return (
    <label className="flex min-w-[140px] flex-col gap-1">
      <span className="px-1 text-[11px] font-semibold uppercase tracking-wide text-stone-400">{label}</span>
      <div className="relative">
        <select
          value={value || ''}
          onChange={(e) => onChange(e.target.value || undefined)}
          className="h-9 w-full cursor-pointer appearance-none rounded-lg border border-stone-200 bg-white px-3 pr-8 text-sm font-medium text-stone-800 outline-none transition-colors hover:border-stone-300 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20"
        >
          <option value="" disabled={!!value}>{placeholder}</option>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
              {o.count !== undefined && ` (${o.count.toLocaleString('en-US')})`}
            </option>
          ))}
        </select>
        <ChevronDown
          size={15}
          className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-stone-400"
        />
      </div>
    </label>
  );
}