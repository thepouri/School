// Convert Skool's loose description markup into safe HTML.
// Supports: [b]/[/b], [i], [u], [s], [ul]/[li], [br], [url=..]/[url], [*]
// Everything else (raw <, >, &, other [tags]) is escaped to plain text.
// Also normalizes stray backslashes before \n and collapses line breaks.

const OPEN_TOKENS = {
  '[b]': '<strong>', '[/b]': '</strong>',
  '[i]': '<em>', '[/i]': '</em>',
  '[u]': '<u>', '[/u]': '</u>',
  '[s]': '<del>', '[/s]': '</del>',
  '[ul]': '<ul class="ml-4 list-disc space-y-0.5">', '[/ul]': '</ul>',
  '[ol]': '<ol class="ml-4 list-decimal space-y-0.5">', '[/ol]': '</ol>',
  '[li]': '<li>', '[/li]': '</li>',
  '[br]': '<br>', '[*]': '<br>',
  '[h1]': '<strong>', '[/h1]': '</strong>',
  '[h2]': '<strong>', '[/h2]': '</strong>',
  '[h3]': '<strong>', '[/h3]': '</strong>',
};

function normalizeBold(s) {
  // Math-bold unicode (e.g. 𝗡𝗼𝗿𝗺𝗮𝗹 𝗽𝗿𝗶𝗰𝗲) → plain text so it renders in
  // the app's own font faces cleanly.
  return s
    .replace(/[\u{1D5D4}-\u{1D5DF}]/gu, (m) => String.fromCharCode(0x41 + (m.codePointAt(0) - 0x1d5d4))) // A-Z
    .replace(/[\u{1D5EE}-\u{1D5F9}]/gu, (m) => String.fromCharCode(0x61 + (m.codePointAt(0) - 0x1d5ee))) // a-z
    .replace(/[\u{1D7CB}-\u{1D7D9}]/gu, (m) => String.fromCharCode(0x30 + (m.codePointAt(0) - 0x1d7cb))); // digits
}

export function formatRichText(input = '') {
  if (!input) return '';
  let s = input;
  // Math-bold unicode → plain.
  s = normalizeBold(s);
  // Normalize common escaped sequences from scraped data.
  s = s.replace(/\\n/g, '\n').replace(/\\t/g, '    ').replace(/\\"/g, '"').replace(/\\\\/g, '\\');
  // Escape HTML to kill any raw markup / injected scripts first.
  s = s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  // Collapse 3+ newlines to 2 (paragraph spacing) and trim blank edges.
  s = s.replace(/\n{3,}/g, '\n\n').replace(/^\s+|\s+$/g, '');
  // Then re-map the allowlisted bbcode to safe HTML.
  for (const [tok, html] of Object.entries(OPEN_TOKENS)) {
    s = s.split(tok).join(html);
  }
  // [url=…] → <a href="…"> (target sanitized: http/https only).
  s = s.replace(/\[url=(.*?)\](.*?)\[\/url\]/g, (_m, href, label) => {
    const clean = href.trim().replace(/&amp;/g, '&');
    if (!/^https?:\/\//i.test(clean)) return label || '';
    return `<a href="${clean}" target="_blank" rel="noopener noreferrer" class="text-brand-600 underline">${label || clean}</a>`;
  });
  s = s.replace(/\[url\](.*?)\[\/url\]/g, (_m, label) => {
    const clean = label.trim();
    if (!/^https?:\/\//i.test(clean)) return label;
    return `<a href="${clean}" target="_blank" rel="noopener noreferrer" class="text-brand-600 underline">${clean}</a>`;
  });
  // Remove any leftover unknown [tags] and stray bracket remnants.
  s = s
    .replace(/\[(?:color|size|quote|code|center|left|right)=?[^\]]*\]/gi, '')
    .replace(/­/g, '') // soft hyphen
    .replace(/[ \t]+/g, ' ');
  return s;
}