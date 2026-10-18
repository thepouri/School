import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Users, GitCompare, DollarSign, ExternalLink } from 'lucide-react';
import CoverArt from './CoverArt.jsx';
import Avatar from './Avatar.jsx';
import Badge from './Badge.jsx';
import { compactNumber, priceLabel, revLabel } from '../lib/format.js';
import { getCompareIds, toggleCompareId, COMPARE_EVENT } from '../lib/compareStore.js';

export default function GroupCard({ group }) {
  const price = priceLabel(group);
  const [compared, setCompared] = useState(() => getCompareIds().includes(group.id));
  const rev = revLabel(group);
  const skoolUrl = group.name ? `https://www.skool.com/${encodeURIComponent(group.name)}` : null;

  // Stay in sync when the selection changes elsewhere (clear bar, other cards).
  useEffect(() => {
    const sync = () => setCompared(getCompareIds().includes(group.id));
    window.addEventListener(COMPARE_EVENT, sync);
    return () => window.removeEventListener(COMPARE_EVENT, sync);
  }, [group.id]);

  const onToggleCompare = (e) => {
    e.preventDefault();
    e.stopPropagation();
    const next = toggleCompareId(group.id);
    setCompared(next.includes(group.id));
  };

  return (
    <Link
      to={`/groups/${group.id}`}
      className="group relative flex flex-col overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md"
    >
      <button
        type="button"
        onClick={onToggleCompare}
        aria-pressed={compared}
        title={compared ? 'Remove from compare' : 'Add to compare'}
        className={`absolute right-2 top-2 z-10 flex h-8 w-8 items-center justify-center rounded-full border shadow-sm transition-colors ${
          compared
            ? 'border-brand-500 bg-brand-500 text-white'
            : 'border-white/70 bg-white/85 text-stone-500 hover:text-brand-600'
        }`}
      >
        <GitCompare size={15} />
      </button>

      {skoolUrl && (
        <a
          href={skoolUrl}
          target="_blank"
          rel="noopener noreferrer"
          title="Open on Skool"
          onClick={(e) => e.stopPropagation()}
          className="absolute right-2 bottom-2 z-10 flex h-8 w-8 items-center justify-center rounded-full border border-white/70 bg-white/85 text-stone-500 shadow-sm transition-colors hover:text-brand-600"
        >
          <ExternalLink size={15} />
        </a>
      )}

      
      <div className="relative">
        <CoverArt
          coverUrl={group.cover_url}
          logoUrl={group.logo_url}
          name={group.display_name}
          color={group.color}
          ratio="aspect-[16/9]"
          className="w-full transition-transform duration-300 group-hover:scale-[1.02]"
        />
        {group.logo_url && /^https?:\/\//.test(group.logo_url) && (
          <Avatar
            src={group.logo_url}
            name={group.display_name}
            size={64}
            color={group.color}
            className="absolute -bottom-5 left-4 border-4 border-white shadow-md"
          />
        )}
      </div>

      <div className="flex flex-1 flex-col px-4 pb-4 pt-7">
        <h3 className="line-clamp-1 text-base font-bold text-stone-900 group-hover:text-brand-600">
          {group.display_name}
        </h3>

        <div className="mt-1.5 flex items-center gap-2 text-sm text-stone-500">
          <Users size={14} className="shrink-0" />
          <span className="font-semibold text-stone-700">{compactNumber(group.total_members)}</span>
          <span>members</span>
          {price && <Badge kind={price.kind}>{price.text}</Badge>}
        </div>

        {rev && (
          <div className="mt-1.5 flex items-center gap-1.5 text-sm text-emerald-700">
            <DollarSign size={13} className="shrink-0" />
            <span className="font-semibold">{rev.text}</span>
            <span className="text-xs text-stone-400">est.</span>
          </div>
        )}

        {group.owner_name && (
          <div className="mt-3 flex items-center gap-1.5 border-t border-stone-100 pt-3 text-xs text-stone-400">
            <span className="truncate">{group.owner_name}</span>
          </div>
        )}
      </div>
    </Link>
  );
}