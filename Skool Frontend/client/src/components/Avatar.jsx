import { useState } from 'react';
import { stringHue } from '../lib/format.js';

// Round avatar with initials fallback on missing/broken image
export default function Avatar({ src, name, size = 40, className = '', onClick, color }) {
  const [failed, setFailed] = useState(false);
  const text = (name || '?').trim();
  const initials = text
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0])
    .join('')
    .toUpperCase();

  const bg = color || `hsl(${stringHue(text)}, 55%, 45%)`;

  if (failed || !src || !/^https?:\/\//.test(src)) {
    return (
      <div
        onClick={onClick}
        className={`inline-flex shrink-0 items-center justify-center rounded-full font-semibold text-white select-none ${className}`}
        style={{ width: size, height: size, backgroundColor: bg, fontSize: size * 0.4 }}
        aria-label={text}
      >
        {initials || '?'}
      </div>
    );
  }
  return (
    <img
      src={src}
      alt={text}
      onClick={onClick}
      onError={() => setFailed(true)}
      className={`inline-block shrink-0 rounded-full object-cover ${className}`}
      style={{ width: size, height: size }}
      loading="lazy"
    />
  );
}