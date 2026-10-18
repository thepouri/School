import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

// Shared between groups & users so the same URL drives both views.
const FILTER_KEYS = [
  // groups
  'search', 'owner', 'category', 'language', 'price', 'visibility',
  'minMembers', 'maxMembers', 'minPosts', 'maxPosts',
  'hasDescription', 'hasLinks', 'hasCourses', 'hasPosts',
  'minPriceUsd', 'maxPriceUsd', 'priceInterval', 'createdFrom', 'createdTo',
  // users
  'location', 'timezone', 'minFollowers', 'maxFollowers',
  'minFollowing', 'maxFollowing', 'minContributions', 'maxContributions',
  'creatorsOnly',
  'isMemberOf', 'isOwnerOf', 'notMemberOf',
  // shared
  'social', 'sort',
];

const BOOL_KEYS = [
  'hasDescription', 'hasLinks', 'creatorsOnly',
  'hasCourses', 'hasPosts',
];

// These params are multi-select: stored as comma-separated values.
const ARRAY_KEYS = [
  'category', 'language', 'social',
  'location', 'timezone', 'isMemberOf', 'isOwnerOf', 'notMemberOf',
];

// Keys kept when clearing filters (view is always kept).
const PRESERVE_KEYS = ['view', 'sort'];

// Single source of truth for the browse page URL state.
// Filter changes write to the URL so views are shareable and back/forward works.
export function useBrowseParams(view) {
  const [searchParams, setSearchParams] = useSearchParams();

  // Parse all known truthy filter keys from the URL
  const filters = {};
  for (const key of FILTER_KEYS) {
    const raw = searchParams.get(key);
    if (raw === null) continue;
    if (ARRAY_KEYS.includes(key)) {
      filters[key] = raw.split(',').map((s) => s.trim()).filter(Boolean);
    } else if (BOOL_KEYS.includes(key)) {
      filters[key] = raw === 'true';
    } else {
      filters[key] = raw;
    }
  }

  const page = Math.max(1, Number.parseInt(searchParams.get('page') || '1', 10) || 1);

  // What gets sent to the API (view is explicit, page only when > 1)
  const params = { view, ...filters };
  if (page > 1) params.page = page;

  const setFilter = useCallback(
    (key, value) => {
      const next = new URLSearchParams(searchParams);
      if (value === undefined || value === null || value === '' ||
          (Array.isArray(value) && value.length === 0)) {
        next.delete(key);
      } else {
        next.set(key, Array.isArray(value) ? value.join(',') : String(value));
      }
      if (key !== 'page') next.set('page', '1'); // any filter change resets pagination
      setSearchParams(next);
    },
    [searchParams, setSearchParams],
  );

  const setPage = useCallback(
    (value) => setFilter('page', value > 1 ? String(value) : undefined),
    [setFilter],
  );

  // Atomically set several filter keys in one URL build (avoids the stale
  // closure that drops earlier keys when changed in the same tick).
  const setFilters = useCallback(
    (patch) => {
      const next = new URLSearchParams(searchParams);
      for (const [key, value] of Object.entries(patch)) {
        if (value === undefined || value === null || value === '' ||
            (Array.isArray(value) && value.length === 0)) {
          next.delete(key);
        } else {
          next.set(key, Array.isArray(value) ? value.join(',') : String(value));
        }
      }
      if (!('page' in patch)) next.set('page', '1');
      setSearchParams(next);
    },
    [searchParams, setSearchParams],
  );

  const clearFilters = useCallback(() => {
    const next = new URLSearchParams();
    for (const key of PRESERVE_KEYS) {
      const v = searchParams.get(key);
      if (v != null) next.set(key, v);
    }
    setSearchParams(next);
  }, [searchParams, setSearchParams]);

  return { filters, setFilter, setFilters, clearFilters, page, setPage, params };
}
