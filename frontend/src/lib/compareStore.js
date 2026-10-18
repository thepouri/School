// Tiny sessionStorage-backed store for the "compare" selection, so the
// selection survives navigation to /compare without polluting the browse URL.
const KEY = 'skool-compare-ids';

export function getCompareIds() {
  try {
    const raw = sessionStorage.getItem(KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr.filter(Boolean) : [];
  } catch {
    return [];
  }
}

export const COMPARE_EVENT = 'skool:compare-change';

export function toggleCompareId(id) {
  const cur = getCompareIds();
  const next = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id];
  try {
    sessionStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new Event(COMPARE_EVENT));
  return next;
}

export function clearCompareIds() {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new Event(COMPARE_EVENT));
}
