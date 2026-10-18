import { useEffect, useState, useRef } from 'react';
import { SlidersHorizontal, X, ChevronDown } from 'lucide-react';
import SearchInput from './filters/SearchInput.jsx';
import FilterSelect from './filters/FilterSelect.jsx';
import ChecklistSelect from './filters/ChecklistSelect.jsx';
import SliderRange from './filters/SliderRange.jsx';
import DateRange from './filters/DateRange.jsx';
import MembershipInput from './filters/MembershipInput.jsx';
import UserTypeahead from './filters/UserTypeahead.jsx';
import PriceFilter from './filters/PriceFilter.jsx';
import { BoolSelect, facetOptions } from './filters/FilterHelpers.jsx';
import { useDebounce } from '../hooks/useDebounce.js';

function sortOptions(kind) {
  if (kind === 'groups') {
    return [
      { value: 'most_members', label: 'Most members' },
      { value: 'fewest_members', label: 'Fewest members' },
      { value: 'most_posts', label: 'Most posts' },
      { value: 'fewest_posts', label: 'Fewest posts' },
      { value: 'engagement', label: 'Engagement (posts/member)' },
      { value: 'rev_desc', label: 'Revenue (high → low)' },
      { value: 'rev_asc', label: 'Revenue (low → high)' },
      { value: 'price_desc', label: 'Price (high → low)' },
      { value: 'price_asc', label: 'Price (low → high)' },
      { value: 'newest', label: 'Newest' },
      { value: 'oldest', label: 'Oldest' },
      { value: 'name', label: 'Name (A-Z)' },
    ];
  }
  return [
    { value: 'most_followers', label: 'Most followers' },
    { value: 'most_contributions', label: 'Most contributions' },
    { value: 'newest', label: 'Newest' },
    { value: 'oldest', label: 'Oldest' },
    { value: 'name', label: 'Name (A-Z)' },
  ];
}

const VISIBILITY_OPTIONS = [
  { value: 'public', label: 'Public' },
  { value: 'private', label: 'Private' },
];

function Field({ label, children }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="px-1 text-[11px] font-semibold uppercase tracking-wide text-stone-400">{label}</span>
      {children}
    </div>
  );
}

function arr(v) {
  return Array.isArray(v) && v.length ? v : null;
}

export default function FilterBar({ view, meta, filters, onChange, onChangeMulti, onClear, resultCount }) {
  const [open, setOpen] = useState(false);
  const [searchTmp, setSearchTmp] = useState(filters.search || '');
  const firstRender = useRef(true);

  // Sync external (URL) search into the temp input only when the change did NOT
  // originate from this box (e.g. back/forward navigation).
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      setSearchTmp(filters.search || '');
    } else {
      setSearchTmp((prev) => (prev === filters.search ? prev : filters.search || ''));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.search]);

  // Debounce typed search into the URL / API query.
  const debouncedSearch = useDebounce(searchTmp, 350);
  const mounted = useRef(false);
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      return; // don't fire the write-back on initial mount
    }
    onChange('search', debouncedSearch.trim() || undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedSearch]);

  const isGroups = view === 'groups';
  const cats = facetOptions(meta?.categories || []);
  const langs = facetOptions(meta?.languages || []);
  const locs = facetOptions(meta?.locations || []);
  const tzs = facetOptions(meta?.timezones || []);
  const userSocials = facetOptions(meta?.socials?.users || []);
  const groupSocials = facetOptions(meta?.socials?.groups || []);

  const activeCount =
    (filters.search ? 1 : 0) +
    (filters.owner ? 1 : 0) +
    (arr(filters.category) ? 1 : 0) +
    (arr(filters.language) ? 1 : 0) +
    (filters.price ? 1 : 0) +
    (filters.priceInterval ? 1 : 0) +
    (filters.minPriceUsd || filters.maxPriceUsd ? 1 : 0) +
    (filters.visibility ? 1 : 0) +
    (filters.minMembers || filters.maxMembers ? 1 : 0) +
    (filters.minPosts || filters.maxPosts ? 1 : 0) +
    (filters.createdFrom || filters.createdTo ? 1 : 0) +
    (filters.hasDescription !== undefined ? 1 : 0) +
    (filters.hasLinks !== undefined ? 1 : 0) +
    (filters.hasCourses !== undefined ? 1 : 0) +
    (filters.hasPosts !== undefined ? 1 : 0) +
    (arr(filters.social) ? 1 : 0) +
    (arr(filters.location) ? 1 : 0) +
    (arr(filters.timezone) ? 1 : 0) +
    (filters.minFollowers || filters.maxFollowers ? 1 : 0) +
    (filters.minFollowing || filters.maxFollowing ? 1 : 0) +
    (filters.minContributions || filters.maxContributions ? 1 : 0) +
    (arr(filters.isMemberOf) ? 1 : 0) +
    (arr(filters.isOwnerOf) ? 1 : 0) +
    (arr(filters.notMemberOf) ? 1 : 0) +
    (filters.creatorsOnly ? 1 : 0);

  const hasAny = activeCount > 0;

  const subLabel = isGroups ? 'Filter communities' : 'Filter people';

  return (
    <div className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
      {/* Top row: name + always-visible primary filters + toggle */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => setOpen(!open)}
          className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg px-3 text-sm font-semibold text-stone-700 transition-colors hover:bg-stone-100"
          aria-expanded={open}
        >
          <SlidersHorizontal size={15} />
          Filters
          {activeCount > 0 && (
            <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-brand-500 px-1.5 text-xs font-bold text-white">
              {activeCount}
            </span>
          )}
          <ChevronDown size={14} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
        </button>

        <SearchInput
          value={searchTmp}
          onChange={(v) => setSearchTmp(v)}
          placeholder={isGroups ? 'Search communities…' : 'Search people…'}
        />

        {isGroups && (
          <UserTypeahead
            value={filters.owner}
            onChange={(v) => onChange('owner', v)}
            placeholder="Search owner…"
          />
        )}

        {resultCount !== undefined && (
          <div className="ml-auto hidden shrink-0 text-sm text-stone-500 md:block">
            <b className="font-semibold text-stone-700">{resultCount.toLocaleString('en-US')}</b>{' '}
            {isGroups ? 'communities' : 'people'}
          </div>
        )}
      </div>

      {/* Collapsible filter group */}
      {open && (
        <div className="mt-4 grid grid-cols-1 items-start gap-x-6 gap-y-5 border-t border-stone-100 pt-4 sm:grid-cols-2 lg:grid-cols-4">
          {isGroups ? (
            <>
              <Field label="Sort by">
                <FilterSelect
                  value={filters.sort}
                  onChange={(v) => onChange('sort', v)}
                  options={sortOptions('groups')}
                  placeholder="Default"
                />
              </Field>
              <Field label="Category">
                <ChecklistSelect
                  noLabel
                  value={filters.category}
                  onChange={(v) => onChange('category', v)}
                  options={cats}
                  placeholder="All categories"
                />
              </Field>
              <Field label="Language">
                <ChecklistSelect
                  noLabel
                  value={filters.language}
                  onChange={(v) => onChange('language', v)}
                  options={langs}
                  placeholder="All languages"
                />
              </Field>
              <Field label="Price">
                <PriceFilter
                  bucketValue={filters.price}
                  onBucket={(v) => onChange('price', v)}
                  intervalValue={filters.priceInterval}
                  onInterval={(v) => onChange('priceInterval', v)}
                  priceFrom={filters.minPriceUsd}
                  priceTo={filters.maxPriceUsd}
                  onPriceFrom={(v) => onChange('minPriceUsd', v)}
                  onPriceTo={(v) => onChange('maxPriceUsd', v)}
                  bounds={meta?.priceBounds}
                />
              </Field>
              <Field label="Visibility">
                <FilterSelect
                  value={filters.visibility}
                  onChange={(v) => onChange('visibility', v)}
                  options={VISIBILITY_OPTIONS}
                  placeholder="Any"
                />
              </Field>
              <Field label="Created">
                <DateRange
                  from={filters.createdFrom}
                  to={filters.createdTo}
                  onFrom={(v) => onChange('createdFrom', v)}
                  onTo={(v) => onChange('createdTo', v)}
                  onPreset={onChangeMulti}
                />
              </Field>
              <div className="min-w-0">
                <SliderRange
                  label="Members"
                  min={1}
                  max={meta?.groupBounds?.members ?? 1000000}
                  scale="log"
                  minValue={filters.minMembers}
                  maxValue={filters.maxMembers}
                  onMin={(v) => onChange('minMembers', v)}
                  onMax={(v) => onChange('maxMembers', v)}
                />
              </div>
              <div className="min-w-0">
                <SliderRange
                  label="Posts"
                  min={1}
                  max={meta?.groupBounds?.posts ?? 20000}
                  scale="log"
                  minValue={filters.minPosts}
                  maxValue={filters.maxPosts}
                  onMin={(v) => onChange('minPosts', v)}
                  onMax={(v) => onChange('maxPosts', v)}
                />
              </div>
              <Field label="Has courses">
                <BoolSelect value={filters.hasCourses} onChange={(v) => onChange('hasCourses', v)} />
              </Field>
              <Field label="Has posts">
                <BoolSelect value={filters.hasPosts} onChange={(v) => onChange('hasPosts', v)} />
              </Field>
              <Field label="Has description">
                <BoolSelect value={filters.hasDescription} onChange={(v) => onChange('hasDescription', v)} />
              </Field>
              <Field label="Has links">
                <BoolSelect value={filters.hasLinks} onChange={(v) => onChange('hasLinks', v)} />
              </Field>
              <Field label="Social link">
                <ChecklistSelect
                  noLabel
                  value={filters.social}
                  onChange={(v) => onChange('social', v)}
                  options={groupSocials}
                  placeholder="Any"
                />
              </Field>
              <Field label="Has member">
                <MembershipInput
                  label="isMemberOf"
                  value={filters.isMemberOf}
                  onChange={(v) => onChange('isMemberOf', v)}
                  placeholder="e.g. sam"
                />
              </Field>
              <Field label="Owned by">
                <MembershipInput
                  label="isOwnerOf"
                  value={filters.isOwnerOf}
                  onChange={(v) => onChange('isOwnerOf', v)}
                  placeholder="e.g. hormozi"
                />
              </Field>
              <Field label="Not a member in">
                <MembershipInput
                  label="notMemberOf"
                  value={filters.notMemberOf}
                  onChange={(v) => onChange('notMemberOf', v)}
                  placeholder="e.g. sam"
                />
              </Field>
            </>
          ) : (
            <>
              <Field label="Sort by">
                <FilterSelect
                  value={filters.sort}
                  onChange={(v) => onChange('sort', v)}
                  options={sortOptions('users')}
                  placeholder="Default"
                />
              </Field>
              <Field label="Location">
                <ChecklistSelect
                  noLabel
                  value={filters.location}
                  onChange={(v) => onChange('location', v)}
                  options={locs}
                  placeholder="All locations"
                />
              </Field>
              <Field label="Time zone">
                <ChecklistSelect
                  noLabel
                  value={filters.timezone}
                  onChange={(v) => onChange('timezone', v)}
                  options={tzs}
                  placeholder="All time zones"
                />
              </Field>
              <Field label="Created">
                <DateRange
                  from={filters.createdFrom}
                  to={filters.createdTo}
                  onFrom={(v) => onChange('createdFrom', v)}
                  onTo={(v) => onChange('createdTo', v)}
                  onPreset={onChangeMulti}
                />
              </Field>
              <div className="min-w-0">
                <SliderRange
                  label="Followers"
                  min={1}
                  max={meta?.userBounds?.followers ?? 100000}
                  scale="log"
                  minValue={filters.minFollowers}
                  maxValue={filters.maxFollowers}
                  onMin={(v) => onChange('minFollowers', v)}
                  onMax={(v) => onChange('maxFollowers', v)}
                />
              </div>
              <div className="min-w-0">
                <SliderRange
                  label="Following"
                  min={1}
                  max={meta?.userBounds?.following ?? 10000}
                  scale="log"
                  minValue={filters.minFollowing}
                  maxValue={filters.maxFollowing}
                  onMin={(v) => onChange('minFollowing', v)}
                  onMax={(v) => onChange('maxFollowing', v)}
                />
              </div>
              <div className="min-w-0">
                <SliderRange
                  label="Contributions"
                  min={1}
                  max={meta?.userBounds?.contributions ?? 10000}
                  scale="log"
                  minValue={filters.minContributions}
                  maxValue={filters.maxContributions}
                  onMin={(v) => onChange('minContributions', v)}
                  onMax={(v) => onChange('maxContributions', v)}
                />
              </div>
              <Field label="Group creators">
                <BoolSelect value={filters.creatorsOnly} onChange={(v) => onChange('creatorsOnly', v)} />
              </Field>
              <Field label="Social link">
                <ChecklistSelect
                  noLabel
                  value={filters.social}
                  onChange={(v) => onChange('social', v)}
                  options={userSocials}
                  placeholder="Any"
                />
              </Field>
            </>
          )}
        </div>
      )}

      {/* Clear bar */}
      {hasAny && (
        <div className="mt-3 flex items-center justify-between border-t border-stone-100 pt-3">
          <button
            onClick={onClear}
            className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-sm font-medium text-stone-500 transition-colors hover:bg-stone-100 hover:text-stone-700"
          >
            <X size={14} />
            Clear all filters
            <span className="text-xs text-stone-400">({subLabel})</span>
          </button>
        </div>
      )}
    </div>
  );
}