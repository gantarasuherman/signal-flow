"use client";

import { useEffect, useState } from "react";
import { AppHeader } from "@/components/AppHeader";
import { Disclaimer } from "@/components/Disclaimer";
import { endpoints } from "@/lib/api";
import { dateTimeWIB, formatPrice, formatUSD, relativeTime } from "@/lib/format";
import { type ThemeChoice, useTheme } from "@/lib/theme";
import type { Health, InstrumentOut, RiskPrefs } from "@/lib/types";

const input =
  "tabular w-full rounded-lg border border-line bg-bg px-3 py-2.5 text-lg outline-none focus:border-fg-soft";
const button = "rounded-lg bg-fg px-4 py-2.5 text-sm font-semibold text-bg disabled:opacity-50";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3 surface rounded-2xl p-4">
      <h2 className="text-lg font-bold">{title}</h2>
      {children}
    </section>
  );
}

function RiskForm() {
  const [prefs, setPrefs] = useState<RiskPrefs | null>(null);
  const [capital, setCapital] = useState("");
  const [risk, setRisk] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    endpoints.risk().then((p) => {
      setPrefs(p);
      setCapital(p.capital?.toString() ?? "");
      setRisk(p.risk_percent.toString());
    });
  }, []);

  const save = async () => {
    try {
      const saved = await endpoints.saveRisk({
        capital: capital ? Number(capital.replace(",", ".")) : null,
        risk_percent: Number(risk.replace(",", ".")),
      });
      setPrefs(saved);
      setMessage("Tersimpan ✓");
    } catch (e) {
      setMessage((e as Error).message);
    }
  };

  return (
    <Section title="Modal & risiko">
      <p className="text-sm text-muted">
        Dipakai untuk menghitung saran ukuran lot di setiap sinyal: kerugian saat kena SL ≈ modal × % risiko.
      </p>
      <label className="block space-y-1">
        <span className="text-sm text-muted">Modal akun (USD)</span>
        <input className={input} inputMode="decimal" placeholder="mis. 1000" value={capital} onChange={(e) => setCapital(e.target.value)} />
      </label>
      <label className="block space-y-1">
        <span className="text-sm text-muted">Risiko per sinyal (%)</span>
        <input className={input} inputMode="decimal" value={risk} onChange={(e) => setRisk(e.target.value)} />
      </label>
      <div className="flex items-center gap-3">
        <button className={button} onClick={save} disabled={!prefs}>
          Simpan
        </button>
        {message && <span className="text-sm text-muted">{message}</span>}
      </div>
      {prefs?.capital && (
        <p className="text-xs text-muted">
          Risiko per sinyal saat ini: {formatUSD((prefs.capital * prefs.risk_percent) / 100)}
        </p>
      )}
    </Section>
  );
}

function InstrumentSettings({ inst, onChange }: { inst: InstrumentOut; onChange: (i: InstrumentOut) => void }) {
  const [brokerPrice, setBrokerPrice] = useState("");
  const [spread, setSpread] = useState(inst.spread_pips.toString());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const run = async (action: () => Promise<InstrumentOut>, success: string): Promise<boolean> => {
    setBusy(true);
    setMessage(null);
    try {
      const updated = await action();
      onChange(updated);
      setSpread(updated.spread_pips.toString());
      setMessage(success);
      return true;
    } catch (e) {
      setMessage((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const calibrated = inst.calibrated_at != null;
  return (
    <div className="space-y-3 rounded-xl bg-bg/60 p-3">
      <div className="flex items-baseline justify-between">
        <div>
          <div className="font-bold">{inst.symbol}</div>
          <div className="text-xs text-muted">{inst.name}</div>
        </div>
        <div className="text-right text-xs">
          {calibrated ? (
            <>
              <div className="tabular text-fg">
                Offset {inst.price_offset >= 0 ? "+" : ""}
                {formatPrice(inst.price_offset, inst.digits)} ({inst.price_offset_pips} pip)
              </div>
              <div className="text-muted">
                Dikalibrasi {relativeTime(inst.calibrated_at!)} · {dateTimeWIB(inst.calibrated_at!)}
              </div>
            </>
          ) : (
            <div className="text-close">Belum dikalibrasi</div>
          )}
        </div>
      </div>

      <div className="flex gap-2">
        <input
          className={input}
          inputMode="decimal"
          placeholder="Harga Sell di broker"
          value={brokerPrice}
          onChange={(e) => setBrokerPrice(e.target.value)}
        />
        <button
          className={button}
          disabled={busy || !brokerPrice}
          onClick={() =>
            run(() => endpoints.calibrate(inst.symbol, Number(brokerPrice.replace(",", "."))), "Kalibrasi tersimpan ✓").then(
              (ok) => ok && setBrokerPrice(""),
            )
          }
        >
          Kalibrasi
        </button>
      </div>
      {calibrated && inst.broker_price != null && (
        <p className="tabular text-xs text-muted">
          Terakhir: broker {formatPrice(inst.broker_price, inst.digits)} vs feed {formatPrice(inst.feed_price, inst.digits)}
        </p>
      )}

      <div className="text-sm text-muted">
        Perkiraan spread (pip) · {inst.spread_is_custom ? "diatur manual" : "bawaan"}
      </div>
      <div className="-mt-1 flex items-center gap-2">
        <input
          className={`${input} text-base`}
          inputMode="decimal"
          value={spread}
          onChange={(e) => setSpread(e.target.value)}
        />
        <button
          className="rounded-lg bg-panel-2 px-3 py-2.5 text-sm"
          disabled={busy}
          onClick={() => run(() => endpoints.updateInstrument(inst.symbol, { spread_pips: Number(spread.replace(",", ".")) }), "Spread tersimpan ✓")}
        >
          Simpan
        </button>
      </div>

      <div className="flex items-center justify-between">
        {message ? <span className="text-xs text-muted">{message}</span> : <span />}
        <div className="flex gap-3 text-xs">
          {inst.spread_is_custom && (
            <button className="text-muted underline" onClick={() => run(() => endpoints.updateInstrument(inst.symbol, { spread_pips: null }), "Spread kembali ke bawaan")}>
              Spread bawaan
            </button>
          )}
          {calibrated && (
            <button className="text-muted underline" onClick={() => run(() => endpoints.resetCalibration(inst.symbol), "Kalibrasi direset")}>
              Reset kalibrasi
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function Calibration() {
  const [items, setItems] = useState<InstrumentOut[]>([]);
  useEffect(() => {
    endpoints.instruments().then(setItems).catch(() => setItems([]));
  }, []);
  return (
    <Section title="Kalibrasi harga ke broker">
      <ol className="list-decimal space-y-1 pl-5 text-sm text-muted">
        <li>
          Buka aplikasi trading Anda (mis. Olymp Trade mode Forex / FXTM), lihat harga yang tampil
          (<strong className="text-fg">Sell/Bid</strong> bila ada dua harga).
        </li>
        <li>Segera ketik harga itu di bawah lalu tekan Kalibrasi.</li>
        <li>Semua harga sinyal & grafik akan disesuaikan ke harga broker Anda.</li>
      </ol>
      <p className="text-xs text-muted">Lakukan saat pasar tenang (bukan saat rilis berita) dan ulangi sesekali.</p>
      <div className="space-y-3">
        {items.map((inst) => (
          <InstrumentSettings
            key={inst.symbol}
            inst={inst}
            onChange={(updated) => setItems((prev) => prev.map((i) => (i.symbol === updated.symbol ? updated : i)))}
          />
        ))}
      </div>
    </Section>
  );
}

function SystemStatus() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    endpoints.health().then(setHealth).catch((e: Error) => setError(e.message));
  }, []);
  const workerOk =
    health?.worker_last_heartbeat != null && Date.now() - new Date(health.worker_last_heartbeat).getTime() < 90_000;
  return (
    <Section title="Status sistem">
      {error && <p className="text-sm text-sell">{error}</p>}
      {health && (
        <ul className="space-y-1 text-sm">
          <li>Database: {health.database ? "✓ OK" : "✗ gagal"}</li>
          <li>Redis: {health.redis ? "✓ OK" : "✗ gagal"}</li>
          <li>Worker: {workerOk ? "✓ aktif" : "✗ tidak ada heartbeat"}</li>
          <li>
            Sumber data: <strong>{health.data_provider}</strong>
            {health.data_provider === "mock" && <span className="text-close"> (data sintetis, bukan harga asli)</span>}
          </li>
        </ul>
      )}
    </Section>
  );
}

function InstallGuide() {
  return (
    <Section title="Pasang di iPhone">
      <ol className="list-decimal space-y-1 pl-5 text-sm text-muted">
        <li>Buka alamat dashboard ini di <strong className="text-fg">Safari</strong>.</li>
        <li>Ketuk tombol <strong className="text-fg">Bagikan</strong> (kotak dengan panah ke atas).</li>
        <li>Pilih <strong className="text-fg">Tambah ke Layar Utama</strong>, lalu Tambah.</li>
      </ol>
      <p className="text-xs text-muted">
        Tidak ada notifikasi: buka SignalFlow saat ingin trading. Aktifkan &quot;Layar tetap menyala&quot; di beranda
        agar layar tidak mati selama memantau sinyal.
      </p>
    </Section>
  );
}

const THEME_OPTIONS: { value: ThemeChoice; label: string; hint: string }[] = [
  { value: "dark", label: "Gelap", hint: "nyaman malam hari" },
  { value: "light", label: "Terang", hint: "jelas di bawah sinar matahari" },
  { value: "system", label: "Ikuti sistem", hint: "mengikuti pengaturan HP" },
];

function Appearance() {
  const { choice, setChoice } = useTheme();
  return (
    <Section title="Tampilan">
      <div className="grid grid-cols-3 gap-2">
        {THEME_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            onClick={() => setChoice(opt.value)}
            className={`rounded-xl border px-2 py-3 text-center transition ${
              choice === opt.value ? "border-brand bg-brand/10 text-fg" : "border-line text-muted"
            }`}
          >
            <div className="text-sm font-semibold">{opt.label}</div>
            <div className="mt-0.5 text-[10px] leading-tight">{opt.hint}</div>
          </button>
        ))}
      </div>
      <p className="text-xs text-muted">Pilihan disimpan di perangkat ini. Tombol ☀/☾ di kanan atas untuk ganti cepat.</p>
    </Section>
  );
}

export default function SettingsPage() {
  return (
    <>
      <AppHeader title="Pengaturan" />
      <main className="mx-auto max-w-3xl space-y-4 px-4 py-4">
        <Appearance />
        <RiskForm />
        <Calibration />
        <InstallGuide />
        <SystemStatus />
        <Disclaimer />
      </main>
    </>
  );
}
