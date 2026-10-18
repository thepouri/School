// Compact numbers: 1_400 -> "1.4K", 3_200_000 -> "3.2M"
export function compactNumber(n) {
  if (n === null || n === undefined) return '0';
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1).replace(/\.0$/, '')}M`;
  if (abs >= 1_000) return `${(n / 1_000).toFixed(abs >= 100_000 ? 0 : 1).replace(/\.0$/, '')}K`;
  return String(n);
}

export function formatNumber(n) {
  return (n ?? 0).toLocaleString('en-US');
}

export function formatDate(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}

// Price label from group price fields:
// "Free" | "$29/month" | "$99 one-time" | "Free trial"
const INTERVAL_LABEL = { month: 'month', year: 'year', one_time: 'one-time', week: 'week' };

export function priceLabel(group) {
  if (!group) return null;
  if (group.price_bucket === 'free') return { text: 'Free', kind: 'free' };

  // Deterministic amount from USD or cents
  let amount = null;
  if (group.price_usd != null && Number(group.price_usd) > 0) {
    amount = Number(group.price_usd);
  } else if (group.price_amount_cents != null && Number(group.price_amount_cents) > 0) {
    amount = Number(group.price_amount_cents) / 100;
  }
  const currency = group.price_currency || 'USD';
  const money =
    amount != null
      ? amount.toLocaleString('en-US', { style: 'currency', currency, maximumFractionDigits: amount % 1 ? 2 : 0 })
      : null;

  if (group.price_bucket === 'free-trial') {
    return { text: money ? `Free trial · ${money}` : 'Free trial', kind: 'free-trial' };
  }
  if (group.price_bucket === 'paid' || money) {
    const interval = INTERVAL_LABEL[group.price_interval] || null;
    const text = interval ? (interval === 'one-time' ? `${money} · one-time` : `${money}/${interval}`) : money;
    return { text: text || 'Paid', kind: 'paid' };
  }
  return null;
}

// Revenue display helper. Reads the interval-normalized keys from the API and
// returns a single formatted string with the correct unit. One `$`, no double.
// month → "$12K/mo"; year → "$1K/mo (yr)"; week → "$5K/mo";
// one_time → "$7.7K/mo (one-time: $71K total)".
const REV_PERIOD_SUFFIX = { month: '/mo', week: '/mo', year: '/mo (yr)' };

export function revLabel(group) {
  if (!group) return null;
  const monthly = group.estimated_monthly_revenue_usd;
  if (group.estimated_rev_period === 'one_time') {
    if (monthly == null || monthly <= 0) return null;
    const total = group.estimated_one_time_revenue_usd;
    return {
      text: total != null ? `$${compactNumber(monthly)}/mo (one-time $${compactNumber(total)})` : `$${compactNumber(monthly)}/mo`,
      period: 'one_time',
    };
  }
  if (monthly == null || monthly <= 0) return null;
  const suffix = REV_PERIOD_SUFFIX[group.estimated_rev_period] || '/mo';
  return { text: `$${compactNumber(monthly)}${suffix}`, period: group.estimated_rev_period || 'month' };
}

// Generate a stable hue from a string for gradient fallbacks
export function stringHue(str = '') {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) % 360;
  return h;
}
