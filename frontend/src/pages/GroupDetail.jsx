import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, BookOpen, DollarSign, ExternalLink, ListChecks, MessageSquare, SearchX, Shield, Users } from 'lucide-react';

import CoverArt from '../components/CoverArt.jsx';
import Avatar from '../components/Avatar.jsx';
import BackLink from '../components/BackLink.jsx';
import Badge from '../components/Badge.jsx';
import Stat from '../components/Stat.jsx';
import LinkList from '../components/LinkList.jsx';
import MetricsChart from '../components/MetricsChart.jsx';
import { compactNumber, formatDate, priceLabel, revLabel } from '../lib/format.js';
import { formatRichText } from '../lib/text.js';
import { useGroup } from '../api/groups.js';

export default function GroupDetail() {
  const { id } = useParams();
  const { data, isLoading, error } = useGroup(id);

  if (isLoading) {
    return (
      <div className="mx-auto max-w-4xl pt-6">
        <div className="aspect-[16/8] animate-pulse rounded-2xl bg-stone-200" />
        <div className="mt-8 space-y-3">
          <div className="h-8 w-2/3 animate-pulse rounded bg-stone-200" />
          <div className="h-4 w-1/2 animate-pulse rounded bg-stone-100" />
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="mx-auto max-w-4xl pt-16 text-center">
        <SearchX size={40} className="mx-auto text-stone-300" />
        <h1 className="mt-4 text-xl font-bold text-stone-800">Community not found</h1>
        <p className="mt-1 text-sm text-stone-500">{error?.message}</p>
        <Link to="/" className="mt-6 inline-flex items-center gap-1 text-sm font-semibold text-brand-600 hover:text-brand-700">
          <ArrowLeft size={15} /> Back to all communities
        </Link>
      </div>
    );
  }

  const g = data;
  const price = priceLabel(g);
  const owner = g.owner;

  return (
    <div className="mx-auto max-w-4xl pt-6 pb-16">
      {/* Back link */}
      <BackLink>Browse communities</BackLink>

      {/* Hero */}
      <div className="overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-sm">
        <CoverArt
          coverUrl={g.cover_url}
          logoUrl={g.logo_url}
          name={g.display_name}
          color={g.color}
          ratio="aspect-[16/8]"
          className="w-full"
        />

        <div className="px-6 pb-6 pt-10 sm:px-8">
          <div className="flex items-end justify-between">
            <div className="flex items-end gap-4">
              <Avatar
                src={g.logo_url}
                name={g.display_name}
                size={96}
                color={g.color}
                className="border-4 border-white shadow-lg"
              />
              <div className="pb-1">
                <h1 className="text-2xl font-bold text-stone-900 sm:text-3xl">{g.display_name}</h1>
                <p className="mt-0.5 flex items-center gap-2 text-sm text-stone-500">
                  @{g.name}
                  {g.name && (
                    <a
                      href={`https://www.skool.com/${encodeURIComponent(g.name)}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-xs font-semibold text-brand-600 hover:text-brand-700"
                    >
                      <ExternalLink size={13} /> Open on Skool
                    </a>
                  )}
                </p>
              </div>
            </div>
            {price && (
              <div className="mb-1">
                <Badge kind={price.kind}>{price.text}</Badge>
              </div>
            )}
          </div>

          {g.description && (
            <div
              className="mt-4 max-w-2xl text-[15px] leading-relaxed text-stone-700"
              dangerouslySetInnerHTML={{ __html: formatRichText(g.description) }}
            />
          )}

          {/* Stats grid */}
          <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {g.total_members != null && (
              <Stat icon={Users} label="Members" value={compactNumber(g.total_members)} />
            )}
            {g.total_posts != null && (
              <Stat icon={MessageSquare} label="Posts" value={compactNumber(g.total_posts)} />
            )}
            {g.num_courses != null && (
              <Stat icon={BookOpen} label="Courses" value={compactNumber(g.num_courses)} />
            )}
            {revLabel(g) && (
              <Stat
                icon={DollarSign}
                label="Est. revenue"
                value={revLabel(g).text}
              />
            )}
            {g.total_admins != null && (
              <Stat icon={Shield} label="Admins" value={compactNumber(g.total_admins)} />
            )}
            {g.total_rules != null && (
              <Stat icon={ListChecks} label="Rules" value={compactNumber(g.total_rules)} />
            )}
          </div>
        </div>
      </div>

      {/* Time-series metrics */}
      <div className="mt-6">
        <MetricsChart kind="groups" id={g.id} />
      </div>

      {/* Meta columns */}
      <div className="mt-6 grid grid-cols-1 gap-6 md:grid-cols-3">
        {/* About */}
        <div className="md:col-span-2">
          <section className="rounded-2xl border border-stone-200 bg-white p-6 shadow-sm">
            <h2 className="text-base font-bold text-stone-900">About this community</h2>
            {g.lp_description ? (
              <div
                className="mt-3 text-[15px] leading-relaxed text-stone-700"
                dangerouslySetInnerHTML={{ __html: formatRichText(g.lp_description) }}
              />
            ) : g.description ? (
              <div
                className="mt-3 text-[15px] leading-relaxed text-stone-700"
                dangerouslySetInnerHTML={{ __html: formatRichText(g.description) }}
              />
            ) : (
              <p className="mt-3 text-sm italic text-stone-400">No description available.</p>
            )}
          </section>

          {g.links?.length > 0 && (
            <section className="mt-6 rounded-2xl border border-stone-200 bg-white p-6 shadow-sm">
              <h2 className="text-base font-bold text-stone-900">Useful links</h2>
              <LinkList links={g.links} className="mt-3" />
            </section>
          )}
        </div>

        {/* Sidebar */}
        <aside className="space-y-6">
          <section className="rounded-2xl border border-stone-200 bg-white p-6 shadow-sm">
            <h2 className="text-base font-bold text-stone-900">Details</h2>
            <dl className="mt-3 space-y-3 text-sm">
              <div className="flex items-center justify-between">
                <dt className="text-stone-500">Price</dt>
                <dd className="font-semibold text-stone-800">{price ? price.text : 'Not listed'}</dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-stone-500">Category</dt>
                <dd className="font-semibold capitalize text-stone-800">
                  {g.category_slug ? g.category_slug.replace(/_/g, ' ') : '—'}
                </dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-stone-500">Language</dt>
                <dd className="font-semibold capitalize text-stone-800">{g.language || '—'}</dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-stone-500">Visibility</dt>
                <dd className="font-semibold capitalize text-stone-800">
                  {g.is_public === true ? 'Public' : g.is_public === false ? 'Private' : 'Unknown'}
                </dd>
              </div>
              {g.created_at && (
                <div className="flex items-center justify-between">
                  <dt className="text-stone-500">Created</dt>
                  <dd className="font-semibold capitalize text-stone-800">{formatDate(g.created_at)}</dd>
                </div>
              )}
            </dl>
          </section>

          {/* Owner card */}
          {owner && owner.id && (
            <section className="rounded-2xl border border-stone-200 bg-white p-6 shadow-sm">
              <h2 className="text-base font-bold text-stone-900">Owner</h2>
              <Link to={`/users/${owner.id}`} className="group mt-4 flex items-center gap-3">
                <Avatar
                  src={owner.avatar}
                  name={owner.full_name || owner.name}
                  size={48}
                />
                <div className="min-w-0">
                  <p className="truncate text-sm font-bold text-stone-900 group-hover:text-brand-600">
                    {owner.full_name || owner.name}
                  </p>
                  <p className="text-xs text-stone-500">@{owner.name}</p>
                  {owner.bio && (
                    <p className="mt-0.5 line-clamp-2 text-xs text-stone-500">{owner.bio}</p>
                  )}
                </div>
              </Link>
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}