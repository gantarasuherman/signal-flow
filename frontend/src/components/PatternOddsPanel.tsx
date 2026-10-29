"use client";

import { useEffect, useMemo, useState } from "react";
import { endpoints } from "@/lib/api";
import { TIMEFRAMES, type PatternOdds, type PatternOddsResponse, type Timeframe } from "@/lib/types";

const TOP = 8;

function Chips<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: readonly T[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap items-center gap-1">
      {options.map((o) => (
        <button
          key={o}
          role="radio"
          aria-checked={o === value}
          onClick={() => onChange(o)}
          className={`rounded-lg px-2.5 py-1 text-xs font-semibold ${
            o === value ? "bg-brand/15 text-brand" : "bg-panel-2 text-muted"
          }`}
        >
          {o}
        </button>
      ))}
    </div>
  );
}

function OddsRow({ r, horizon }: { r: PatternOdds; horizon: number }) {
  const up = r.direction === "naik";
  const pct = Math.round(r.chance * 100);
  return (
    <li className="space-y-1 rounded-xl bg-panel-2 px-3 py-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="min-w-0 truncate text-sm font-bold">{r.name}</span>
        <span className={`tabular shrink-0 text-lg font-black ${up ? "text-buy" : "text-sell"}`}>{pct}%</span>
      </div>
      {/* bar: 50% = lempar koin, makin penuh makin kuat */}
      <div className="h-1.5 overflow-hidden rounded-full bg-line">
        <div className={`h-full rounded-full ${up ? "bg-buy" : "bg-sell"}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="flex flex-wrap gap-x-2 text-[11px] text-muted">
        <span className="font-semibold text-fg-soft">
          {r.symbol} · {r.timeframe}
        </span>
        <span>
          {r.samples}× dalam {horizon} candle
        </span>
        {!r.follows_pattern && (
          <span className="text-warn">pola {r.bias > 0 ? "naik" : "turun"} yang sering gagal ({Math.round(r.probability * 100)}% benar)</span>
        )}
      </div>
    </li>
  );
}

/**
 * Pola dengan peluang historis terbesar (naik / turun) per instrumen & timeframe, dari data
 * ±1 tahun di database. Pola yang sering gagal dihitung ke arah sebaliknya.
 */
export function PatternOddsPanel() {
  const [data, setData] = useState<PatternOddsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [symbol, setSymbol] = useState("Semua");
  const [tf, setTf] = useState<"Semua" | Timeframe>("Semua");
  const [onlyReliable, setOnlyReliable] = useState(true);

  useEffect(() => {
    endpoints
      .patternOdds()
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, []);

  const symbols = useMemo(() => ["Semua", ...new Set(data?.rows.map((r) => r.symbol) ?? [])], [data]);
  const rows = (data?.rows ?? []).filter(
    (r) => (symbol === "Semua" || r.symbol === symbol) && (tf === "Semua" || r.timeframe === tf) && (!onlyReliable || r.reliable),
  );
  const up = rows.filter((r) => r.direction === "naik").slice(0, TOP);
  const down = rows.filter((r) => r.direction === "turun").slice(0, TOP);

  return (
    <div className="space-y-3 rounded-xl border border-line p-3">
      <div>
        <h3 className="font-bold">Pola paling berpotensi (data historis)</h3>
        <p className="text-[12px] leading-snug text-muted">
          Seberapa sering harga benar-benar naik / turun dalam {data?.horizon ?? 4} candle setelah pola muncul, dihitung
          dari ±1 tahun data instrumen ini. 50% = sama dengan lempar koin.
        </p>
      </div>

      <div className="space-y-1.5">
        <Chips label="Instrumen" options={symbols} value={symbol} onChange={setSymbol} />
        <Chips label="Timeframe" options={["Semua", ...TIMEFRAMES] as const} value={tf} onChange={setTf} />
        <label className="flex items-center gap-2 text-xs text-fg-soft">
          <input type="checkbox" checked={onlyReliable} onChange={(e) => setOnlyReliable(e.target.checked)} />
          Hanya yang meyakinkan (≥{Math.round((data?.min_edge ?? 0.55) * 100)}% dan lolos uji statistik)
        </label>
      </div>

      {error && <p className="text-xs text-err">{error}</p>}
      {!data && !error && <div className="h-32 animate-pulse rounded-xl bg-panel-2" />}

      {data && (
        <div className="grid gap-3 sm:grid-cols-2">
          {(
            [
              ["▲ Potensi naik", up, "text-buy"],
              ["▼ Potensi turun", down, "text-sell"],
            ] as const
          ).map(([title, list, tone]) => (
            <div key={title} className="space-y-1.5">
              <h4 className={`text-sm font-bold ${tone}`}>{title}</h4>
              {list.length ? (
                <ul className="space-y-1.5">
                  {list.map((r) => (
                    <OddsRow key={`${r.symbol}-${r.timeframe}-${r.name}`} r={r} horizon={data.horizon} />
                  ))}
                </ul>
              ) : (
                <p className="rounded-xl bg-panel-2 px-3 py-2 text-xs text-muted">
                  Tidak ada pola yang {onlyReliable ? "cukup meyakinkan" : "tercatat"} untuk pilihan ini.
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      <p className="text-[11px] leading-snug text-muted">
        Hanya pola dengan minimal {data?.min_samples ?? 30} kejadian. Peluang ini mencerminkan kondisi pasar setahun
        terakhir (mis. tren naik USDJPY membuat pola naik lebih sering benar) dan bisa berubah. Gunakan sebagai konfirmasi
        bersama tren & SL, bukan satu-satunya alasan masuk.
      </p>
    </div>
  );
}
