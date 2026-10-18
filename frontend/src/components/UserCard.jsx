import { Link } from 'react-router-dom';
import { MapPin, Users, PenSquare, ExternalLink } from 'lucide-react';
import Avatar from './Avatar.jsx';
import { compactNumber } from '../lib/format.js';

export default function UserCard({ user }) {
  const skoolUrl = user.name ? `https://www.skool.com/@${encodeURIComponent(user.name)}` : null;
  return (
    <Link
      to={`/users/${user.id}`}
      className="group relative flex flex-col items-center rounded-2xl border border-stone-200 bg-white p-6 text-center shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md"
    >
      {skoolUrl && (
        <a
          href={skoolUrl}
          target="_blank"
          rel="noopener noreferrer"
          title="Open on Skool"
          onClick={(e) => e.stopPropagation()}
          className="absolute right-2 top-2 z-10 flex h-8 w-8 items-center justify-center rounded-full border border-stone-200 bg-white/85 text-stone-400 shadow-sm transition-colors hover:text-brand-600"
        >
          <ExternalLink size={15} />
        </a>
      )}
      <Avatar
        src={user.avatar_bubble_url || user.avatar_url}
        name={user.full_name || user.name}
        size={80}
        className="transition-transform duration-200 group-hover:scale-105"
      />
      <h3 className="mt-4 line-clamp-2 text-base font-bold text-stone-900 group-hover:text-brand-600">
        {user.full_name || user.name}
      </h3>
      {user.location && (
        <div className="mt-1 flex items-center justify-center gap-1 text-sm text-stone-500">
          <MapPin size={13} className="shrink-0" />
          <span className="truncate">{user.location}</span>
        </div>
      )}

      <div className="mt-4 flex items-center justify-center gap-4 border-t border-stone-100 pt-4 text-sm">
        <span className="flex items-center gap-1.5 font-medium text-stone-600">
          <Users size={14} className="text-stone-400" />
          <b className="text-stone-900">{compactNumber(user.total_followers)}</b> followers
        </span>
        <span className="flex items-center gap-1.5 font-medium text-stone-600">
          <PenSquare size={14} className="text-stone-400" />
          <b className="text-stone-900">{compactNumber(user.total_contributions)}</b>
        </span>
      </div>
    </Link>
  );
}