import { useEffect, useRef, useState } from 'react';
import SearchInput from './SearchInput.jsx';
import { useDebounce } from '../../hooks/useDebounce.js';

// Typeahead input for person-based membership filters.
// value is an array of user slugs (or null); onChange(array | null).
// Suggests PEOPLE via /api/users/suggest; clicking a suggestion appends
// the user's slug to the list and clears the typed text.
const KEY_LABELS = {
  isMemberOf: 'Has member',
  isOwnerOf: 'Owned by',
  notMemberOf: 'Not a member in',
};

export default function MembershipInput({ label, value, onChange, placeholder }) {
  const list = Array.isArray(value) ? value : [];
  // Authoritative committed list — appends merge into this ref synchronously so
  // rapid successive picks never drop an earlier slug while the parent prop
  // lags behind (URL write → re-render round-trip).
  const committedRef = useRef(list);
  const [tmp, setTmp] = useState('');
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

  // Commits happen via: suggestion picks (appendSuggestion), an explicit
  // comma-terminated list (typed "a, b, " commits ["a","b"]), or clearing the
  // field (empty text → null, so the filter clears). A debounced auto-commit
  // of raw partial text raced with value-sync from the URL and was silently
  // deleting the filter (that single-user bug).
  const debouncedList = useDebounce(tmp, 350);
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      committedRef.current = list;
      return;
    }
    // Cleared field → clear the filter.
    if (!debouncedList.trim()) {
      if (committedRef.current.length) {
        committedRef.current = [];
        onChange(null);
      }
      return;
    }
    // Commit a typed list only when the last token is terminated by a comma
    // (an explicit commit). Trailing partial text waits for a pick.
    if (!/,\s*$/.test(debouncedList)) return;
    const final = debouncedList.split(',').map((s) => s.trim()).filter(Boolean);
    if (final.join(',') !== committedRef.current.join(',')) {
      committedRef.current = final;
      onChange(final.length ? final : null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedList]);

  // Sync external (URL) changes back into the input (clear-all, back/forward).
  useEffect(() => {
    committedRef.current = list;
    setTmp((prev) => {
      const prevJoined = prev.split(',').map((s) => s.trim()).filter(Boolean).join(', ');
      return prevJoined === list.join(', ') ? prev : list.join(', ');
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  // Fetch person suggestions for the last comma-separated token.
  const lastToken = tmp.split(',').pop()?.trim() || '';
  const debouncedQ = useDebounce(lastToken, 250);
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

  const appendSuggestion = (slug) => {
    // Merge into the synchronously-tracked committed list, so rapid successive
    // picks never lose an earlier slug even if the parent prop lags.
    const parts = committedRef.current.includes(slug) ? committedRef.current : [...committedRef.current, slug];
    committedRef.current = parts;
    setTmp(parts.join(', '));
    setShow(false);
    // Commit immediately so the URL filter updates without waiting for debounce.
    onChange(parts);
  };

  const shortLabel = KEY_LABELS[label] || label;

  return (
    <div ref={wrapRef} className="relative">
      <SearchInput
        value={tmp}
        onChange={setTmp}
        placeholder={placeholder || shortLabel}
      />
      {show && suggestions.length > 0 && (
        <div className="absolute left-0 top-full z-30 mt-1 w-full overflow-hidden rounded-lg border border-stone-200 bg-white shadow-lg">
          {suggestions.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => appendSuggestion(s.name)}
              className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left hover:bg-brand-50"
            >
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium text-stone-800">
                  {s.full_name}
                </span>
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