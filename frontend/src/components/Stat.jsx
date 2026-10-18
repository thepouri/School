export default function Stat({ icon, label, value }) {
  const Icon = icon;
  return (
    <div className="flex items-center gap-3 rounded-xl border border-stone-200 bg-white px-4 py-3">
      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-stone-100 text-stone-500">
        <Icon size={18} />
      </div>
      <div className="min-w-0">
        <div className="text-lg font-bold leading-tight text-stone-900">{value}</div>
        <div className="truncate text-xs font-medium text-stone-500">{label}</div>
      </div>
    </div>
  );
}