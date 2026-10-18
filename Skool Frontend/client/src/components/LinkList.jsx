import { ArrowUpRight } from 'lucide-react';

// Group "useful links" rendered as list of buttons
export default function LinkList({ links, className = '' }) {
  if (!links || links.length === 0) return null;
  return (
    <ul className={`space-y-2 ${className}`}>
      {links.map((l, i) => {
        const url = safeUrl(l.url);
        if (!url) return null;
        const host = new URL(url).hostname.replace(/^www\./, '');
        const inner = (
          <>
            <span className="flex-1 truncate">
              <span className="block truncate">{l.label || host}</span>
              <span className="block truncate text-xs font-normal text-stone-400">{host}</span>
            </span>
            <ArrowUpRight size={15} className="shrink-0 text-stone-400" />
          </>
        );
        return (
          <li key={i}>
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-sm font-medium text-stone-700 transition-colors hover:border-brand-300 hover:bg-brand-50 hover:text-brand-700"
            >
              {inner}
            </a>
          </li>
        );
      })}
    </ul>
  );
}

function safeUrl(u) {
  if (!u || typeof u !== 'string') return null;
  try {
    const parsed = new URL(u);
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') return u;
  } catch {
    /* not a URL */
  }
  return null;
}