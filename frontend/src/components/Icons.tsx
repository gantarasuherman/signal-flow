// Ikon garis sederhana (gaya Lucide), mengikuti warna teks (currentColor).
type IconProps = { className?: string };

const base = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  viewBox: "0 0 24 24",
};

export const ChartIcon = ({ className = "h-5 w-5" }: IconProps) => (
  <svg {...base} className={className} aria-hidden>
    <path d="M3 3v18h18" />
    <path d="M7 15v-4M11 17V7M15 13v-3M19 11V5" />
  </svg>
);

export const HistoryIcon = ({ className = "h-5 w-5" }: IconProps) => (
  <svg {...base} className={className} aria-hidden>
    <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
    <path d="M3 3v5h5M12 7v5l3 2" />
  </svg>
);

export const FlaskIcon = ({ className = "h-5 w-5" }: IconProps) => (
  <svg {...base} className={className} aria-hidden>
    <path d="M9 3h6M10 3v6L4.5 18.5A2 2 0 0 0 6.2 21h11.6a2 2 0 0 0 1.7-2.5L14 9V3" />
    <path d="M7 15h10" />
  </svg>
);

export const SettingsIcon = ({ className = "h-5 w-5" }: IconProps) => (
  <svg {...base} className={className} aria-hidden>
    <path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z" />
    <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
  </svg>
);

export const SunIcon = ({ className = "h-5 w-5" }: IconProps) => (
  <svg {...base} className={className} aria-hidden>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </svg>
);

export const MoonIcon = ({ className = "h-5 w-5" }: IconProps) => (
  <svg {...base} className={className} aria-hidden>
    <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
  </svg>
);

/** Logo SignalFlow: tiga candle (hijau-merah-hijau) dalam kotak membulat. */
export const Logo = ({ className = "h-8 w-8" }: IconProps) => (
  <svg viewBox="0 0 32 32" className={className} aria-hidden>
    <rect width="32" height="32" rx="9" fill="var(--panel-2)" />
    <path d="M9 9v14" stroke="var(--buy)" strokeWidth="1.6" strokeLinecap="round" />
    <rect x="7" y="12" width="4" height="7" rx="1" fill="var(--buy)" />
    <path d="M16 7v15" stroke="var(--sell)" strokeWidth="1.6" strokeLinecap="round" />
    <rect x="14" y="10" width="4" height="6" rx="1" fill="var(--sell)" />
    <path d="M23 6v16" stroke="var(--buy)" strokeWidth="1.6" strokeLinecap="round" />
    <rect x="21" y="8" width="4" height="10" rx="1" fill="var(--buy)" />
  </svg>
);

export const BookIcon = ({ className = "h-5 w-5" }: IconProps) => (
  <svg {...base} className={className} aria-hidden>
    <path d="M4 19.5V5a2 2 0 0 1 2-2h14v16H6.5a2.5 2.5 0 0 0 0 5H20" />
    <path d="M8 7h8M8 11h5" />
  </svg>
);
