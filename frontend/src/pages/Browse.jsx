import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { GitCompare, X } from 'lucide-react';

import { CardGrid } from '../components/CardGrid.jsx';
import FilterBar from '../components/FilterBar.jsx';
import GroupCard from '../components/GroupCard.jsx';
import UserCard from '../components/UserCard.jsx';
import Pagination from '../components/Pagination.jsx';
import { useBrowseParams } from '../hooks/useBrowseParams.js';
import { useMeta } from '../api/meta.js';
import { useGroups } from '../api/groups.js';
import { useUsers } from '../api/users.js';
import { getCompareIds, clearCompareIds, COMPARE_EVENT } from '../lib/compareStore.js';

const PAGE_SIZE = 24;

export default function Browse() {
  const [searchParams] = useSearchParams();
  const view = searchParams.get('view') === 'users' ? 'users' : 'groups';

  const { filters, setFilter, setFilters, clearFilters, page, setPage, params } = useBrowseParams(view);
  const { data: meta } = useMeta();

  const query = useMemo(
    () => ({ ...params, page, pageSize: PAGE_SIZE }),
    [params, page],
  );

  const groupsQuery = useGroups(view === 'groups' ? query : undefined);
  const usersQuery = useUsers(view === 'users' ? query : undefined);

  const isLoading = view === 'groups' ? groupsQuery.isLoading : usersQuery.isLoading;
  const isError = view === 'groups' ? groupsQuery.isError : usersQuery.isError;
  const error = view === 'groups' ? groupsQuery.error : usersQuery.error;
  const data = view === 'groups' ? groupsQuery.data : usersQuery.data;

  const resultCount = data?.pagination?.total;

  // Compare selection (groups view only) — re-read on each render so card
  // toggles are reflected. Listen for toggle events to bump state.
  const [compareTick, setCompareTick] = useState(0);
  useEffect(() => {
    const bump = () => setCompareTick((t) => t + 1);
    window.addEventListener(COMPARE_EVENT, bump);
    return () => window.removeEventListener(COMPARE_EVENT, bump);
  }, []);
  const compareIds = view === 'groups' ? getCompareIds() : [];

  const items = useMemo(() => {
    if (!data) return [];
    return data.items.map((item) =>
      view === 'groups' ? <GroupCard key={item.id} group={item} /> : <UserCard key={item.id} user={item} />,
    );
  }, [data, view]);

  return (
    <div className="pb-16">
      <div className="py-8">
        <h1 className="text-3xl font-bold tracking-tight text-stone-900">
          {view === 'groups' ? 'Explore communities' : 'Discover people'}
        </h1>
        <p className="mt-1 text-[15px] text-stone-500">
          {view === 'groups'
            ? 'Find the community that fits your goals — filter by category, language, price, size and more.'
            : 'Find creators and members building across Skool — follow their work and communities.'}
        </p>
      </div>

      <FilterBar
        view={view}
        meta={meta}
        filters={filters}
        onChange={setFilter}
        onChangeMulti={setFilters}
        onClear={clearFilters}
        resultCount={resultCount}
      />

      <div className="mt-8">
        <CardGrid
          loading={isLoading && !data}
          error={isError && !data ? error : null}
          emptyTitle={view === 'groups' ? 'No communities match your filters' : 'No people match your filters'}
          emptyHint="Try widening your filters or clearing the search."
        >
          {!isLoading && items}
        </CardGrid>
      </div>

      {data?.pagination && (
        <Pagination pagination={data.pagination} onPage={setPage} />
      )}

      {/* Floating compare bar */}
      {compareIds.length > 0 && (
        <div className="fixed bottom-5 left-1/2 z-40 flex -translate-x-1/2 items-center gap-3 rounded-full border border-stone-200 bg-white px-4 py-2.5 shadow-lg">
          <GitCompare size={16} className="text-brand-500" />
          <span className="text-sm font-semibold text-stone-700">
            {compareIds.length} selected
          </span>
          <Link
            to={`/compare?ids=${compareIds.join(',')}`}
            className="rounded-full bg-brand-500 px-3.5 py-1.5 text-sm font-semibold text-white transition-colors hover:bg-brand-600"
          >
            Compare
          </Link>
          <button
            type="button"
            onClick={clearCompareIds}
            aria-label="Clear compare selection"
            className="flex h-7 w-7 items-center justify-center rounded-full text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-600"
          >
            <X size={14} />
          </button>
        </div>
      )}
    </div>
  );
}