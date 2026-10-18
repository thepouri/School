import { useState } from 'react';
import { stringHue } from '../lib/format.js';

// Cover image with layered fallback: image → logo → gradient + initials
export default function CoverArt({ coverUrl, logoUrl, name, color, className = '', ratio = 'aspect-[16/9]' }) {
  const [failed, setFailed] = useState(false);
  const [logoFailed, setLogoFailed] = useState(false);
  const fallbackColor = color || `hsl(${stringHue(name)}, 55%, 45%)`;

  // Layer 1: real cover image
  if (!failed && coverUrl && /^https?:\/\//.test(coverUrl)) {
    return (
      <img
        src={coverUrl}
        alt={name}
        onError={() => setFailed(true)}
        className={`card-img object-cover ${ratio} ${className}`}
        loading="lazy"
      />
    );
  }

  // Layer 2: logo as the background
  if (!logoFailed && logoUrl && /^https?:\/\//.test(logoUrl)) {
    return (
      <img
        src={logoUrl}
        alt={name}
        onError={() => setLogoFailed(true)}
        className={`object-cover ${ratio} ${className}`}
        loading="lazy"
      />
    );
  }

  // Layer 3: brand gradient + initials
  const text = (name || '?').trim();
  const initials = text
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0])
    .join('')
    .toUpperCase();

  return (
    <div
      className={`flex items-center justify-center ${ratio} ${className}`}
      style={{
        background: `linear-gradient(135deg, ${fallbackColor}, ${fallbackColor}cc)`,
      }}
    >
      {initials && (
        <span
          className="font-extrabold text-white/90 select-none"
          style={{ fontSize: 'clamp(2rem, 6vw, 3.5rem)' }}
        >
          {initials}
        </span>
      )}
    </div>
  );
}