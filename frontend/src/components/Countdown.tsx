"use client";

import { useEffect, useState } from "react";
import { countdown } from "@/lib/format";
import { useRealtime } from "@/lib/realtime";

const M15_MS = 15 * 60 * 1000;

/** Hitung mundur ke tutupnya candle M15 berikutnya (memakai jam server). */
export function Countdown({ compact = false }: { compact?: boolean }) {
  const { clockOffset } = useRealtime();
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    const tick = () => setNow(Date.now() + clockOffset);
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [clockOffset]);

  if (now == null) return null;
  const remaining = (Math.ceil(now / M15_MS) * M15_MS - now) / 1000;
  const urgent = remaining <= 60;

  return (
    <div className={`tabular text-right leading-tight ${urgent ? "text-close" : "text-fg"}`}>
      {!compact && <div className="text-[10px] uppercase tracking-wide text-muted">Candle M15 berikutnya</div>}
      <div className={compact ? "text-sm font-semibold" : "text-lg font-semibold"}>{countdown(remaining)}</div>
    </div>
  );
}
