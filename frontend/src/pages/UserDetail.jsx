import { Link, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  BadgeCheck,
  ExternalLink,
  Globe,
  Instagram,
  Linkedin,
  MapPin,
  SearchX,
  Twitter,
  Youtube,
} from 'lucide-react';

import Avatar from '../components/Avatar.jsx';
import BackLink from '../components/BackLink.jsx';
import Badge from '../components/Badge.jsx';
import GroupCard from '../components/GroupCard.jsx';
import MetricsChart from '../components/MetricsChart.jsx';
import { compactNumber } from '../lib/format.js';
import { useUser } from '../api/users.js';

const SOCIAL_ICONS = {
  link_website: { icon: Globe, label: 'Website' },
  link_twitter: { icon: Twitter, label: 'X / Twitter' },
  link_linkedin: { icon: Linkedin, label: 'LinkedIn' },
  link_youtube: { icon: Youtube, label: 'YouTube' },
  link_instagram: { icon: Instagram, label: 'Instagram' },
  link_facebook: null, // no clean brand icon; skip
};

function groupSectionTitle(count, kind) {
  return kind === 'owned' ? `Communities they own (${count})` : `Communities they're in (${count})`;
}

export default function UserDetail() {
  const { id } = useParams();
  const { data, isLoading, error } = useUser(id);

  if (isLoading) {
    return (
      <div className="mx-auto max-w-4xl pt-6">
        <div className="flex items-center gap-5">
          <div className="h-24 w-24 animate-pulse rounded-full bg-stone-200" />
          <div className="flex-1 space-y-2">
            <div className="h-7 w-1/2 animate-pulse rounded bg-stone-200" />
            <div className="h-4 w-1/3 animate-pulse rounded bg-stone-100" />
          </div>
        </div>
        <div className="mt-8 grid grid-cols-1 gap-5 md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="aspect-[16/9] animate-pulse rounded-2xl bg-stone-200" />
          ))}
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="mx-auto max-w-4xl pt-16 text-center">
        <SearchX size={40} className="mx-auto text-stone-300" />
        <h1 className="mt-4 text-xl font-bold text-stone-800">Person not found</h1>
        <p className="mt-1 text-sm text-stone-500">{error?.message}</p>
        <Link to="/" className="mt-6 inline-flex items-center gap-1 text-sm font-semibold text-brand-600 hover:text-brand-700">
          <ArrowLeft size={15} /> Back to browse
        </Link>
      </div>
    );
  }

  const u = data.user;
  const displayName = u.full_name || u.name;
  // Server exposes social links as a single `links` object keyed by network.
  const socialIds = ['website', 'twitter', 'linkedin', 'youtube', 'instagram', 'facebook'];
  const socials = socialIds
    .map((id) => ({ id, def: SOCIAL_ICONS['link_' + id] }))
    .filter((s) => s.def && u.links?.[s.id])
    .map((s) => ({ ...s.def, key: s.id, url: u.links[s.id] }));

  return (
    <div className="mx-auto max-w-4xl pt-6 pb-16">
      <BackLink>Browse people</BackLink>

      {/* Profile hero */}
      <section className="rounded-2xl border border-stone-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="flex flex-col gap-6 sm:flex-row sm:items-start">
          <Avatar
            src={u.avatar_bubble_url || u.avatar_url}
            name={displayName}
            size={120}
            className="shrink-0"
          />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-bold text-stone-900 sm:text-3xl">{displayName}</h1>
              <BadgeCheck size={22} className="text-brand-500" />
            </div>
            <p className="mt-0.5 flex items-center gap-2 text-sm text-stone-500">
              @{u.name}
              {u.name && (
                <a
                  href={`https://www.skool.com/@${encodeURIComponent(u.name)}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-xs font-semibold text-brand-600 hover:text-brand-700"
                >
                  <ExternalLink size={13} /> Open on Skool
                </a>
              )}
            </p>

            {u.bio && <p className="mt-3 whitespace-pre-line text-[15px] leading-relaxed text-stone-700">{u.bio}</p>}

            <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-stone-500">
              {u.location && (
                <span className="inline-flex items-center gap-1.5">
                  <MapPin size={14} /> {u.location}
                </span>
              )}
              {u.timezone && <span className="inline-flex items-center gap-1.5">🕐 {u.timezone}</span>}
            </div>

            {socials.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-2">
                {socials.map((s) => (
                  <a
                    key={s.key}
                    href={s.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 rounded-full border border-stone-200 bg-stone-50 px-3 py-1.5 text-xs font-semibold text-stone-700 transition-colors hover:border-brand-300 hover:text-brand-700"
                  >
                    <s.icon size={13} />
                    {s.label}
                  </a>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Stat row */}
        <div className="mt-8 grid grid-cols-3 gap-3 border-t border-stone-100 pt-6">
          <div className="rounded-xl bg-stone-50 px-4 py-3 text-center">
            <div className="text-2xl font-bold text-stone-900">
              {compactNumber(u.total_followers)}
            </div>
            <div className="text-xs font-medium text-stone-500">Followers</div>
          </div>
          <div className="rounded-xl bg-stone-50 px-4 py-3 text-center">
            <div className="text-2xl font-bold text-stone-900">
              {compactNumber(u.total_following)}
            </div>
            <div className="text-xs font-medium text-stone-500">Following</div>
          </div>
          <div className="rounded-xl bg-stone-50 px-4 py-3 text-center">
            <div className="text-2xl font-bold text-stone-900">
              {compactNumber(u.total_contributions)}
            </div>
            <div className="text-xs font-medium text-stone-500">Contributions</div>
          </div>
        </div>
      </section>

      {/* Time-series metrics */}
      <div className="mt-6">
        <MetricsChart kind="users" id={u.id} />
      </div>

      {/* Owned communities */}
      <section className="mt-10">
        <h2 className="flex items-center gap-2 text-lg font-bold text-stone-900">
          {groupSectionTitle(data.ownedCount, 'owned')}
          <Badge kind="ownership">Ownership</Badge>
        </h2>
        {data.ownedGroups.length ? (
          <div className="mt-4 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {data.ownedGroups.map((g) => (
              <GroupCard key={g.id} group={g} />
            ))}
          </div>
        ) : (
          <p className="mt-4 text-sm italic text-stone-400">Not an owner of any community.</p>
        )}
      </section>

      {/* Member communities */}
      <section className="mt-10">
        <h2 className="flex items-center gap-2 text-lg font-bold text-stone-900">
          {groupSectionTitle(data.memberCount, 'member')}
          <Badge kind="membership">Membership</Badge>
        </h2>
        {data.memberGroups.length ? (
          <div className="mt-4 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {data.memberGroups.map((g) => (
              <GroupCard key={g.id} group={g} />
            ))}
          </div>
        ) : (
          <p className="mt-4 text-sm italic text-stone-400">Not a member of any community.</p>
        )}
      </section>
    </div>
  );
}