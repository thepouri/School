import { SearchX } from 'lucide-react';

// Responsive grid with skeleton / empty / error states
export function CardGrid({ children, loading, count = 8, error, emptyTitle, emptyHint, gridClass = '' }) {
  if (loading) {
    return (
      <div className={`grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 ${gridClass}`}>
        {Array.from({ length: count }).map((_, i) => (
          <div key={i} className="animate-pulse overflow-hidden rounded-2xl border border-stone-200 bg-white">
            <div className="aspect-[16/9] bg-stone-200" />
            <div className="space-y-2 p-4">
              <div className="h-4 w-3/4 rounded bg-stone-200" />
              <div className="h-3 w-1/2 rounded bg-stone-100" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl border border-red-200 bg-red-50 px-6 py-10 text-center">
        <p className="font-semibold text-red-700">Something went wrong</p>
        <p className="mt-1 text-sm text-red-500">{error.message}</p>
      </div>
    );
  }

  if (!children || children.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-stone-300 bg-white px-6 py-16 text-center">
        <SearchX size={36} className="text-stone-300" />
        <p className="mt-4 text-lg font-semibold text-stone-700">{emptyTitle || 'No results found'}</p>
        <p className="mt-1 text-sm text-stone-500">{emptyHint || 'Try adjusting your filters.'}</p>
      </div>
    );
  }

  return (
    <div className={`grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 ${gridClass}`}>
      {children}
    </div>
  );
}