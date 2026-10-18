import { Users, LayoutGrid } from 'lucide-react';

// Segmented control: Groups | People
export default function BrowseToggle({ view, onChange }) {
  const base =
    'relative inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-sm font-semibold transition-colors';
  const active = 'bg-brand-500 text-white shadow-sm';
  const inactive = 'text-stone-600 hover:text-stone-900';

  return (
    <div className="inline-flex rounded-full border border-stone-200 bg-white p-1 shadow-sm" role="tablist">
      <button
        role="tab"
        aria-selected={view === 'groups'}
        onClick={() => onChange('groups')}
        className={`${base} ${view === 'groups' ? active : inactive}`}
      >
        <LayoutGrid size={16} />
        Communities
      </button>
      <button
        role="tab"
        aria-selected={view === 'users'}
        onClick={() => onChange('users')}
        className={`${base} ${view === 'users' ? active : inactive}`}
      >
        <Users size={16} />
        People
      </button>
    </div>
  );
}