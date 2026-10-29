"use client";

import Link from "next/link";
import { Countdown } from "./Countdown";
import { Logo, MoonIcon, SunIcon } from "./Icons";
import { WakeLockToggle } from "./WakeLockToggle";
import { useRealtime } from "@/lib/realtime";
import { useTheme } from "@/lib/theme";

const STATUS = {
  open: { color: "bg-buy", label: "Live" },
  connecting: { color: "bg-close animate-pulse", label: "Menyambung…" },
  closed: { color: "bg-sell", label: "Terputus" },
} as const;

export function ThemeToggle() {
  const { resolved, toggle } = useTheme();
  const dark = resolved === "dark";
  return (
    <button
      onClick={toggle}
      aria-label={dark ? "Ganti ke tema terang" : "Ganti ke tema gelap"}
      className="surface grid h-9 w-9 place-items-center rounded-full text-fg-soft transition hover:text-fg"
    >
      {dark ? <SunIcon className="h-[18px] w-[18px]" /> : <MoonIcon className="h-[18px] w-[18px]" />}
    </button>
  );
}

export function AppHeader({
  title,
  subtitle,
  back,
  showWakeLock = false,
}: {
  title: string;
  subtitle?: string;
  back?: string;
  showWakeLock?: boolean;
}) {
  const { status } = useRealtime();
  const s = STATUS[status];
  return (
    <header className="safe-top sticky top-0 z-20 border-b border-line bg-bg/85 backdrop-blur-xl">
      <div className="mx-auto flex max-w-3xl items-center gap-3 px-4 py-3">
        {back ? (
          <Link href={back} aria-label="Kembali" className="-ml-2 rounded-full p-2 text-2xl leading-none text-muted">
            ‹
          </Link>
        ) : (
          <Logo className="h-9 w-9 shrink-0" />
        )}
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-xl font-bold tracking-tight">{title}</h1>
          <div className="flex items-center gap-1.5 text-xs text-muted">
            <span className={`inline-block h-2 w-2 rounded-full ${s.color}`} />
            <span>{s.label}</span>
            {subtitle && <span className="truncate">· {subtitle}</span>}
          </div>
          {showWakeLock && (
            <div className="mt-1">
              <WakeLockToggle />
            </div>
          )}
        </div>
        <Countdown />
        <ThemeToggle />
      </div>
    </header>
  );
}
