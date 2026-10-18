// Shared card wrapper for analytics charts.
export default function chartCard({ title, subtitle, insight, children }) {
  return (
    <section className="flex flex-col rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
      <header>
        <h2 className="text-base font-bold text-stone-900">{title}</h2>
        {subtitle && <p className="mt-0.5 text-xs text-stone-500">{subtitle}</p>}
      </header>
      <div className="mt-4 flex-1">{children}</div>
      {insight && (
        <p className="mt-4 rounded-lg bg-brand-50 px-3 py-2 text-xs leading-relaxed text-brand-700">
          💡 {insight}
        </p>
      )}
    </section>
  );
}
