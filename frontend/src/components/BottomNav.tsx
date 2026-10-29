"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookIcon, ChartIcon, FlaskIcon, HistoryIcon, SettingsIcon } from "./Icons";

const ITEMS = [
  { href: "/", label: "Grafik", Icon: ChartIcon },
  { href: "/history", label: "Riwayat", Icon: HistoryIcon },
  { href: "/backtest", label: "Backtest", Icon: FlaskIcon },
  { href: "/panduan", label: "Panduan", Icon: BookIcon },
  { href: "/settings", label: "Pengaturan", Icon: SettingsIcon },
];

export function BottomNav() {
  const pathname = usePathname();
  return (
    <nav className="safe-bottom fixed inset-x-0 bottom-0 z-30 border-t border-line bg-bg/90 backdrop-blur-xl">
      <div className="mx-auto grid max-w-3xl grid-cols-5 px-1">
        {ITEMS.map(({ href, label, Icon }) => {
          const active = href === "/" ? pathname === "/" || pathname.startsWith("/instrument") : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`relative flex flex-col items-center gap-1 py-2 text-[11px] font-medium transition ${
                active ? "text-fg" : "text-muted"
              }`}
            >
              {active && <span className="absolute top-0 h-0.5 w-8 rounded-full bg-brand" />}
              <span className={`grid h-8 w-11 place-items-center rounded-full transition ${active ? "bg-brand/15 text-brand" : ""}`}>
                <Icon />
              </span>
              {label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
