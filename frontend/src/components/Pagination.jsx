import { ArrowLeft, ArrowRight } from 'lucide-react';

function pageList(current, total) {
  const pages = new Set([1, total]);
  for (let p = current - 1; p <= current + 1; p++) {
    if (p >= 1 && p <= total) pages.add(p);
  }
  return [...pages].sort((a, b) => a - b);
}

export default function Pagination({ pagination, onPage }) {
  if (!pagination || pagination.totalPages <= 1) return null;
  const { page, totalPages, total } = pagination;
  const list = pageList(page, totalPages);

  const btn =
    'inline-flex h-9 items-center gap-1 rounded-lg border border-stone-200 bg-white px-3 text-sm font-medium text-stone-600 transition-colors hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-40';

  return (
    <nav className="mt-10 flex flex-col items-center justify-between gap-4 border-t border-stone-200 pt-6 sm:flex-row">
      <p className="text-sm text-stone-500">
        Showing <span className="font-semibold text-stone-700">{total.toLocaleString('en-US')}</span> results
        {totalPages > 1 && (
          <>
            {' '}· page <span className="font-semibold text-stone-700">{page}</span> of{' '}
            <span className="font-semibold text-stone-700">{totalPages.toLocaleString('en-US')}</span>
          </>
        )}
      </p>

      <div className="flex items-center gap-1">
        <button className={btn} onClick={() => onPage(page - 1)} disabled={page <= 1} aria-label="Previous page">
          <ArrowLeft size={15} />
          Prev
        </button>
        {list.map((p, i) => {
          const prev = list[i - 1];
          const gap = prev !== undefined && p - prev > 1;
          return (
            <span key={p} className="flex items-center">
              {gap && <span className="px-1.5 text-sm text-stone-400">…</span>}
              <button
                onClick={() => onPage(p)}
                aria-current={p === page ? 'page' : undefined}
                className={`h-9 min-w-9 rounded-lg px-2 text-sm font-semibold transition-colors ${
                  p === page
                    ? 'bg-brand-500 text-white shadow-sm'
                    : 'text-stone-600 hover:bg-stone-100'
                }`}
              >
                {p}
              </button>
            </span>
          );
        })}
        <button className={btn} onClick={() => onPage(page + 1)} disabled={page >= totalPages} aria-label="Next page">
          Next
          <ArrowRight size={15} />
        </button>
      </div>
    </nav>
  );
}