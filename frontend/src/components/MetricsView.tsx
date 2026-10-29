import type { Metrics } from "@/lib/types";

const num = (v: number | null | undefined, digits = 1, suffix = "") =>
  v == null ? "—" : `${v.toFixed(digits)}${suffix}`;
const signed = (v: number, digits = 1, suffix = "") => `${v > 0 ? "+" : ""}${v.toFixed(digits)}${suffix}`;
const tone = (v: number | null | undefined) =>
  v == null || v === 0 ? "text-fg" : v > 0 ? "text-buy" : "text-sell";

/** Kotak ringkasan metrik utama (untuk HP: 2 kolom, angka besar). */
export function MetricsGrid({ m }: { m: Metrics }) {
  const items: [string, string, string][] = [
    ["Jumlah trade", String(m.trades), "text-fg"],
    ["Win rate", num(m.win_rate, 1, "%"), "text-fg"],
    ["Profit factor", num(m.profit_factor, 2), tone(m.profit_factor == null ? null : m.profit_factor - 1)],
    ["Total", `${signed(m.total_r, 1, "R")} · ${signed(m.net_pips, 0)} pip`, tone(m.total_r)],
    ["Max drawdown", `${m.max_drawdown_pct.toFixed(1)}% (${m.max_drawdown_r.toFixed(1)}R)`, "text-sell"],
    ["Rata-rata R:R", `${num(m.avg_rr_realized, 2)} (rencana ${num(m.avg_rr_planned, 1)})`, "text-fg"],
    ["Expectancy", num(m.expectancy_r, 2, "R / trade"), tone(m.expectancy_r)],
    ["Sharpe", num(m.sharpe, 2), tone(m.sharpe)],
  ];
  return (
    <dl className="grid grid-cols-2 gap-2">
      {items.map(([label, value, color]) => (
        <div key={label} className="rounded-xl bg-bg/60 px-3 py-2">
          <dt className="text-[11px] text-muted">{label}</dt>
          <dd className={`tabular text-base font-bold ${color}`}>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Tabel ringkas beberapa baris metrik (mis. per instrumen / per jendela waktu). */
export function MetricsTable({ rows }: { rows: { label: string; m: Metrics; highlight?: boolean }[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="tabular w-full min-w-[520px] text-right text-xs">
        <thead className="text-muted">
          <tr>
            <th className="py-1 text-left font-normal" />
            <th className="font-normal">Trade</th>
            <th className="font-normal">Win%</th>
            <th className="font-normal">PF</th>
            <th className="font-normal">Total R</th>
            <th className="font-normal">Pip</th>
            <th className="font-normal">DD%</th>
            <th className="font-normal">Sharpe</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ label, m, highlight }) => (
            <tr key={label} className={`border-t border-line ${highlight ? "font-bold" : ""}`}>
              <td className="py-1.5 text-left">{label}</td>
              <td>{m.trades}</td>
              <td>{num(m.win_rate, 0)}</td>
              <td className={tone(m.profit_factor == null ? null : m.profit_factor - 1)}>{num(m.profit_factor, 2)}</td>
              <td className={tone(m.total_r)}>{signed(m.total_r, 1)}</td>
              <td className={tone(m.net_pips)}>{signed(m.net_pips, 0)}</td>
              <td>{m.max_drawdown_pct.toFixed(1)}</td>
              <td>{num(m.sharpe, 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
