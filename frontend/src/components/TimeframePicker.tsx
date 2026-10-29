"use client";

import { TIMEFRAMES, type Timeframe } from "@/lib/types";

const LABEL: Record<Timeframe, string> = { M1: "1 menit", M5: "5 menit", M15: "15 menit", H1: "1 jam", H4: "4 jam" };

interface Props {
  value: Timeframe;
  onChange: (tf: Timeframe) => void;
  disabled?: boolean;
}

/** Pilihan timeframe entry untuk analisis AI (M1 hingga H4). */
export function TimeframePicker({ value, onChange, disabled }: Props) {
  return (
    <div role="radiogroup" aria-label="Timeframe analisis AI" className="flex items-center gap-1">
      <span className="mr-1 text-[11px] text-muted">Timeframe</span>
      {TIMEFRAMES.map((t) => (
        <button
          key={t}
          role="radio"
          aria-checked={t === value}
          title={LABEL[t]}
          onClick={() => onChange(t)}
          disabled={disabled}
          className={`rounded-lg px-2.5 py-1 text-xs font-semibold disabled:opacity-50 ${
            t === value ? "bg-ai text-bg" : "bg-panel-2 text-muted"
          }`}
        >
          {t}
        </button>
      ))}
    </div>
  );
}
