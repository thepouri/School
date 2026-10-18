import { Search, X } from 'lucide-react';

export default function SearchInput({ value, onChange, placeholder = 'Search…' }) {
  return (
    <div className="relative min-w-[200px]">
      <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-stone-400" />
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="h-9 w-full rounded-lg border border-stone-200 bg-white pl-9 pr-8 text-sm font-medium text-stone-800 outline-none transition-colors placeholder:font-normal placeholder:text-stone-400 hover:border-stone-300 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20"
      />
      {value && (
        <button
          onClick={() => onChange('')}
          aria-label="Clear search"
          className="absolute right-2 top-1/2 flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded-full bg-stone-200 text-stone-500 hover:bg-stone-300"
        >
          <X size={12} />
        </button>
      )}
    </div>
  );
}