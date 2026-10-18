import { Crown } from 'lucide-react';

const STYLES = {
  free: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  paid: 'bg-amber-50 text-amber-700 border-amber-200',
  'free-trial': 'bg-brand-50 text-brand-700 border-brand-100',
  ownership: 'bg-brand-50 text-brand-700 border-brand-100',
  membership: 'bg-violet-50 text-violet-700 border-violet-200',
  default: 'bg-stone-100 text-stone-600 border-stone-200',
};

export default function Badge({ kind, children, icon }) {
  const cls = STYLES[kind] || STYLES.default;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${cls}`}>
      {icon ? <Crown size={12} /> : null}
      {children}
    </span>
  );
}