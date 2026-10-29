"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useState } from "react";
import { AppHeader } from "@/components/AppHeader";
import { MetricsGrid, MetricsTable } from "@/components/MetricsView";
import { endpoints } from "@/lib/api";
import { dateTimeWIB, dayMonthWIB, relativeTime } from "@/lib/format";
import type { BacktestRun, BacktestSection, Metrics } from "@/lib/types";

const EquityChart = dynamic(() => import("@/components/EquityChart"), { ssr: false });

const STATUS_LABEL: Record<BacktestRun["status"], string> = {
  queued: "mengantre",
  running: "berjalan…",
  done: "selesai",
  failed: "gagal",
};

function verdict(m: Metrics): { text: string; tone: string } {
  if (m.trades < 30) return { text: "Trade terlalu sedikit untuk disimpulkan", tone: "text-muted" };
  if ((m.profit_factor ?? 0) >= 1.2 && (m.expectancy_r ?? 0) > 0.05)
    return { text: "Menguntungkan pada periode ini", tone: "text-buy" };
  if ((m.profit_factor ?? 0) >= 1) return { text: "Sekitar impas — belum meyakinkan", tone: "text-close" };
  return { text: "Rugi pada periode ini — jangan dipakai untuk uang sungguhan", tone: "text-sell" };
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3 surface rounded-2xl p-4">
      <h2 className="text-lg font-bold">{title}</h2>
      {children}
    </section>
  );
}

function SectionResult({ s }: { s: BacktestSection }) {
  const split = Math.floor(new Date(s.out_of_sample.start).getTime() / 1000);
  return (
    <>
      <EquityChart points={s.equity} splitTime={split} />
      <p className="text-[11px] text-muted">
        Kurva modal (100 = awal) bila risiko tetap per sinyal. Garis kuning = awal out-of-sample.
      </p>
      <MetricsTable
        rows={[
          { label: "Semua", m: s.all, highlight: true },
          { label: "In-sample", m: s.in_sample },
          { label: "Out-of-sample", m: s.out_of_sample },
          ...s.windows.map((w, i) => ({
            label: `Periode ${i + 1} (${dayMonthWIB(w.start)})`,
            m: w,
          })),
        ]}
      />
    </>
  );
}

function RunDetail({ run }: { run: BacktestRun }) {
  const s = run.summary;
  const [symbol, setSymbol] = useState<string>("PORTOFOLIO");
  if (!s) return null;
  const section = symbol === "PORTOFOLIO" ? s.portfolio : s.instruments[symbol];
  const inst = symbol === "PORTOFOLIO" ? null : s.instruments[symbol];
  const v = verdict(section.all);
  const oos = verdict(section.out_of_sample);

  return (
    <div className="space-y-4">
      <Section title={`Hasil backtest #${run.id}`}>
        <p className="text-sm text-muted">
          {dateTimeWIB(s.period.start)} → {dateTimeWIB(s.period.end)} · strategi {s.strategy.name} · risiko{" "}
          {s.settings.risk_percent}% per sinyal
        </p>
        <div className="flex flex-wrap gap-1">
          {["PORTOFOLIO", ...Object.keys(s.instruments)].map((sym) => (
            <button
              key={sym}
              onClick={() => setSymbol(sym)}
              className={`rounded-full px-3 py-1.5 text-sm ${sym === symbol ? "bg-fg text-bg" : "bg-bg text-muted"}`}
            >
              {sym === "PORTOFOLIO" ? "Semua" : sym}
            </button>
          ))}
        </div>
        <div className="rounded-xl bg-bg/60 px-3 py-2 text-sm">
          <div className={`font-bold ${v.tone}`}>Keseluruhan: {v.text}</div>
          <div className={oos.tone}>Out-of-sample: {oos.text}</div>
        </div>
        <MetricsGrid m={section.all} />
        <SectionResult s={section} />
        {inst && (
          <p className="text-xs text-muted">
            {inst.strategy && <>Strategi <strong>{inst.strategy.name}</strong> · </>}Biaya: spread {inst.costs.spread_pips} pip + slippage {inst.costs.slippage_pips} pip (masuk & keluar) · data M15{" "}
            {inst.coverage.M15?.candles.toLocaleString("id-ID")} candle
          </p>
        )}
      </Section>

      {inst?.optimization && (
        <Section title="Optimasi parameter (anti-overfitting)">
          <p className="text-sm text-muted">{inst.optimization.note}</p>
          <p className="tabular text-sm">
            Terbaik di in-sample:{" "}
            {Object.entries(inst.optimization.best_params)
              .map(([k, val]) => `${k}=${val}`)
              .join(", ")}
          </p>
          <MetricsTable
            rows={[
              { label: "In-sample", m: inst.optimization.best_in_sample },
              { label: "Out-of-sample", m: inst.optimization.best_out_of_sample, highlight: true },
            ]}
          />
        </Section>
      )}

      {inst && (
        <Section title="Trade terakhir">
          <ul className="tabular space-y-1 text-xs">
            {inst.trades
              .slice(-30)
              .reverse()
              .map((t) => (
                <li key={t.entry_time} className="flex justify-between gap-2 border-b border-line py-1">
                  <span className="text-muted">{dateTimeWIB(t.entry_time)}</span>
                  <span className={t.action === "BUY" ? "text-buy" : "text-sell"}>{t.action}</span>
                  <span className="text-muted">{t.status}</span>
                  <span className={t.r >= 0 ? "text-buy" : "text-sell"}>
                    {t.r >= 0 ? "+" : ""}
                    {t.r.toFixed(2)}R
                  </span>
                </li>
              ))}
          </ul>
        </Section>
      )}

      <ul className="space-y-1 text-xs text-muted">
        {s.notes.map((n) => (
          <li key={n}>• {n}</li>
        ))}
      </ul>
    </div>
  );
}

export default function BacktestPage() {
  const [runs, setRuns] = useState<BacktestRun[]>([]);
  const [selected, setSelected] = useState<BacktestRun | null>(null);
  const [days, setDays] = useState(365);
  const [optimize, setOptimize] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadList = useCallback(async () => {
    try {
      const list = await endpoints.backtests();
      setRuns(list);
      return list;
    } catch (e) {
      setError((e as Error).message);
      return [];
    }
  }, []);

  const open = useCallback(async (id: number) => {
    try {
      setSelected(await endpoints.backtest(id));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    loadList().then((list) => {
      const latestDone = list.find((r) => r.status === "done");
      if (latestDone) void open(latestDone.id);
    });
  }, [loadList, open]);

  // Pantau run yang sedang berjalan
  const active = runs.find((r) => r.status === "queued" || r.status === "running");
  useEffect(() => {
    if (!active) return;
    const id = setInterval(async () => {
      const list = await loadList();
      const run = list.find((r) => r.id === active.id);
      if (run && (run.status === "done" || run.status === "failed")) void open(run.id);
    }, 5000);
    return () => clearInterval(id);
  }, [active, loadList, open]);

  const start = async () => {
    setError(null);
    try {
      await endpoints.startBacktest({ days, optimize });
      await loadList();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <>
      <AppHeader title="Backtest" subtitle="Uji strategi di data historis" />
      <main className="mx-auto max-w-3xl space-y-4 px-4 py-4">
        <Section title="Jalankan backtest">
          <div className="flex flex-wrap items-center gap-2">
            {[90, 180, 365].map((d) => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`rounded-lg px-3 py-2 text-sm ${d === days ? "bg-fg text-bg" : "bg-bg text-muted"}`}
              >
                {d} hari
              </button>
            ))}
          </div>
          <label className="flex items-center gap-2 text-sm text-muted">
            <input type="checkbox" checked={optimize} onChange={(e) => setOptimize(e.target.checked)} />
            Optimasi parameter di in-sample, uji di out-of-sample (lebih lama, ±10 menit)
          </label>
          <button
            onClick={start}
            disabled={!!active}
            className="rounded-lg bg-fg px-4 py-2.5 text-sm font-semibold text-bg disabled:opacity-50"
          >
            {active ? `Backtest #${active.id} ${STATUS_LABEL[active.status]}` : "Mulai backtest"}
          </button>
          <p className="text-xs text-muted">
            Memakai strategi & parameter di config/strategies.yaml, spread & slippage per instrumen. 70% awal = in-sample,
            30% akhir = out-of-sample (data yang &quot;belum pernah dilihat&quot;).
          </p>
          {error && <p className="text-sm text-sell">{error}</p>}
        </Section>

        {selected?.status === "done" && <RunDetail run={selected} />}
        {selected?.status === "failed" && (
          <p className="rounded-xl bg-sell/10 px-4 py-3 text-sm text-err">
            Backtest #{selected.id} gagal: {selected.error}
          </p>
        )}

        {runs.length > 0 && (
          <Section title="Riwayat backtest">
            <ul className="space-y-1 text-sm">
              {runs.map((r) => (
                <li key={r.id}>
                  <button
                    disabled={r.status !== "done" && r.status !== "failed"}
                    onClick={() => open(r.id)}
                    className={`flex w-full justify-between rounded-lg px-3 py-2 text-left ${selected?.id === r.id ? "bg-panel-2" : "bg-bg/60"}`}
                  >
                    <span>
                      #{r.id} · {r.request.days} hari{r.request.optimize ? " · optimasi" : ""}
                    </span>
                    <span className="text-muted">
                      {STATUS_LABEL[r.status]} · {relativeTime(r.created_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </Section>
        )}
      </main>
    </>
  );
}
