import { useEffect, useRef, useState } from 'react';
import SearchInput from './SearchInput.jsx';
import { useDebounce } from '../../hooks/useDebounce.js';

// Single-select user typeahead. Used for "owner" (communities owned by a
// person). `value` is a user slug (or undefined); onChange(slug | undefined).
// Suggests PEOPLE via /api/users/suggest; clicking a suggestion commits the slug.
export default function UserTypeahead({ value, onChange, placeholder }) {
  const [tmp, setTmp] = useState(value || '');
  const [suggestions, setSuggestions] = useState([]);
  const [show, setShow] = useState(false);
  const mounted = useRef(false);
  const wrapRef = useRef(null);

  // Close dropdown on outside click.
  useEffect(() => {
    if (!show) return;
    const onDown = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setShow(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [show]);

  // Debounce the typed text into the URL filter. Only fire on the first run
  // (write-back guard) so external URL changes don't loop.
  const debounced = useDebounce(tmp, 350);
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    onChange(debounced.trim() || undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);

  // Sync external (URL) value back into the box.
  useEffect(() => {
    setTmp((prev) => (prev === (value || '') ? prev : value || ''));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  // Fetch person suggestions for the typed token.
  const debouncedQ = useDebounce(tmp, 250);
  useEffect(() => {
    if (debouncedQ.length < 2) {
      setSuggestions([]);
      setShow(false);
      return;
    }
    let cancelled = false;
    fetch(`/api/users/suggest?q=${encodeURIComponent(debouncedQ)}`)
      .then((r) => r.json())
      .then((rows) => {
        if (cancelled) return;
        setSuggestions(Array.isArray(rows) ? rows : []);
        setShow(true);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [debouncedQ]);

  const pick = (slug) => {
    setTmp(slug);
    setShow(false);
    onChange(slug);
  };

  return (
    <div ref={wrapRef} className="relative">
      <SearchInput value={tmp} onChange={setTmp} placeholder={placeholder} />
      {show && suggestions.length > 0 && (
        <div className="absolute left-0 top-full z-30 mt-1 w-full overflow-hidden rounded-lg border border-stone-200 bg-white shadow-lg">
          {suggestions.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => pick(s.name)}
              className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left hover:bg-brand-50"
            >
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium text-stone-800">{s.full_name}</span>
                <span className="block text-xs text-stone-400">@{s.name}</span>
              </span>
              {s.total_followers != null && (
                <span className="shrink-0 text-xs tabular-nums text-stone-400">
                  {s.total_followers.toLocaleString('en-US')} followers
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
