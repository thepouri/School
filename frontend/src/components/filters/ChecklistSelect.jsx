import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown } from 'lucide-react';

// Multi-select checklist dropdown. `value` is an array (or null).
// options: [{ value, label, count }], onChange(array | null).
export default function ChecklistSelect({
  label,
  value,
  onChange,
  options,
  placeholder = 'Any',
  className = '',
  noLabel = false,
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const selected = Array.isArray(value) ? value : [];
  const selectedSet = new Set(selected);

  const toggle = (v) => {
    const next = new Set(selectedSet);
    if (next.has(v)) next.delete(v);
    else next.add(v);
    onChange(next.size ? [...next] : null);
  };

  const allOn =
    selectedSet.size === options.length &&
    options.length > 0 &&
    options.every((o) => selectedSet.has(o.value));

  const toggleAll = () => onChange(allOn ? null : options.map((o) => o.value));
  const clear = () => onChange(null);

  const summary = selected.length ? selected.map((v) => titleize(v)).join(', ') : placeholder;

  return (
    <div ref={wrapRef} className={`relative min-w-[150px] ${className}`}>
      {!noLabel && (
        <span className="px-1 text-[11px] font-semibold uppercase tracking-wide text-stone-400">{label}</span>
      )}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="listbox"
        className={`mt-1 flex h-9 w-full items-center justify-between gap-1 rounded-lg border bg-white px-3 text-sm font-medium outline-none transition-colors hover:border-stone-300 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 ${
          selected.length ? 'border-brand-300 text-stone-800' : 'border-stone-200 text-stone-500'
        }`}
      >
        <span className="truncate">{summary}</span>
        <span className="flex shrink-0 items-center gap-1.5">
          {selected.length > 0 && (
            <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-brand-500 px-1.5 text-xs font-bold text-white">
              {selected.length}
            </span>
          )}
          <ChevronDown size={14} className={`text-stone-400 transition-transform ${open ? 'rotate-180' : ''}`} />
        </span>
      </button>

      {open && (
        <div className="absolute left-0 top-full z-30 mt-1 max-h-80 w-max min-w-[200px] max-w-[300px] overflow-auto rounded-lg border border-stone-200 bg-white p-1.5 shadow-lg">
          <div className="flex items-center justify-between gap-2 border-b border-stone-100 px-2 pb-1.5">
            <button
              type="button"
              onClick={toggleAll}
              className="text-xs font-semibold text-brand-600 hover:text-brand-700"
            >
              {allOn ? 'Clear all' : 'Select all'}
            </button>
            {selected.length > 0 && (
              <button
                type="button"
                onClick={clear}
                className="text-xs font-medium text-stone-400 hover:text-stone-600"
              >
                Clear
              </button>
            )}
          </div>
          {options.map((o) => {
            const checked = selectedSet.has(o.value);
            return (
              <label
                key={o.value}
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 hover:bg-stone-50"
              >
                <span
                  className={`flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded border transition-colors ${
                    checked ? 'border-brand-500 bg-brand-500' : 'border-stone-300 bg-white'
                  }`}
                >
                  {checked && <Check size={12} className="text-white" strokeWidth={3} />}
                </span>
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={checked}
                  onChange={() => toggle(o.value)}
                />
                <span className="flex-1 truncate text-sm font-medium text-stone-700">{o.label}</span>
                {o.count !== undefined && (
                  <span className="shrink-0 text-xs tabular-nums text-stone-400">
                    {o.count.toLocaleString('en-US')}
                  </span>
                )}
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}

function titleize(s = '') {
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}