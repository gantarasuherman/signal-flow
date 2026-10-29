"use client";

import Link from "next/link";
import { useState } from "react";
import { AppHeader } from "@/components/AppHeader";
import { Disclaimer } from "@/components/Disclaimer";

// ---------- gambar candle mini ----------

/** [open, high, low, close] dalam skala 0–100 (100 = harga tertinggi). */
type Bar = [number, number, number, number];

/** Candle konteks (pudar) sebelum pola. */
const DOWN: Bar[] = [
  [86, 88, 74, 76],
  [76, 78, 64, 66],
  [66, 68, 54, 56],
];
const UP: Bar[] = [
  [14, 26, 12, 24],
  [24, 36, 22, 34],
  [34, 46, 32, 44],
];

function Candles({ context = [], bars }: { context?: Bar[]; bars: Bar[] }) {
  const all = [...context.map((b) => ({ b, faded: true })), ...bars.map((b) => ({ b, faded: false }))];
  const step = 16;
  const width = all.length * step + 8;
  // Rentang vertikal mengikuti data agar candle tampil besar
  const hi = Math.max(...all.map(({ b }) => b[1])) + 4;
  const lo = Math.min(...all.map(({ b }) => b[2])) - 4;
  const y = (v: number) => hi - v;
  const height = 110;
  return (
    <svg
      viewBox={`0 0 ${width} ${hi - lo}`}
      height={height}
      width={(width * height) / (hi - lo)}
      className="max-w-full"
      aria-hidden
    >
      {all.map(({ b: [o, h, l, c], faded }, i) => {
        const x = 4 + i * step + step / 2;
        const color = c >= o ? "var(--buy)" : "var(--sell)";
        const top = y(Math.max(o, c));
        const height = Math.max(Math.abs(c - o), 1.5);
        return (
          <g key={i} opacity={faded ? 0.3 : 1}>
            <line x1={x} x2={x} y1={y(h)} y2={y(l)} stroke={color} strokeWidth={1.5} />
            <rect x={x - 5} y={top} width={10} height={height} rx={1} fill={color} />
          </g>
        );
      })}
    </svg>
  );
}

// ---------- data pola ----------

type Bias = "naik" | "turun" | "ragu";

interface PatternGuide {
  name: string;
  bias: Bias;
  candles: number;
  context?: Bar[];
  bars: Bar[];
  look: string;
  meaning: string;
  tip: string;
}

const PATTERNS: PatternGuide[] = [
  {
    name: "Hammer",
    bias: "naik",
    candles: 1,
    context: DOWN,
    bars: [[46, 51, 22, 50]],
    look: "Badan kecil di bagian atas, sumbu bawah minimal 2× badan, sumbu atas sangat pendek. Muncul setelah harga turun.",
    meaning: "Penjual sempat menekan jauh ke bawah, tetapi pembeli mendorong harga kembali naik sebelum candle tutup.",
    tip: "Paling bermakna di support / Bollinger bawah. Tunggu candle berikutnya ditutup di atas high Hammer.",
  },
  {
    name: "Inverted Hammer",
    bias: "naik",
    candles: 1,
    context: DOWN,
    bars: [[26, 52, 24, 30]],
    look: "Badan kecil di bagian bawah, sumbu atas panjang, setelah harga turun.",
    meaning: "Pembeli mulai mencoba menaikkan harga; tekanan jual mulai berkurang.",
    tip: "Lebih lemah dari Hammer. Wajib konfirmasi candle hijau berikutnya.",
  },
  {
    name: "Hanging Man",
    bias: "turun",
    candles: 1,
    context: UP,
    bars: [[58, 60, 34, 55]],
    look: "Bentuknya sama dengan Hammer, tetapi muncul setelah harga NAIK.",
    meaning: "Muncul tekanan jual besar di puncak kenaikan; pembeli mulai lelah.",
    tip: "Konfirmasi: candle berikutnya merah dan ditutup di bawah badan Hanging Man.",
  },
  {
    name: "Shooting Star",
    bias: "turun",
    candles: 1,
    context: UP,
    bars: [[48, 76, 46, 45]],
    look: "Badan kecil di bawah, sumbu atas panjang, setelah harga naik.",
    meaning: "Pembeli mendorong tinggi lalu ditolak keras oleh penjual.",
    tip: "Kuat bila sumbu atasnya menembus resistance / Bollinger atas lalu ditolak.",
  },
  {
    name: "Morning Star",
    bias: "naik",
    candles: 3,
    bars: [
      [80, 82, 50, 52],
      [48, 50, 40, 45],
      [47, 78, 46, 76],
    ],
    look: "Merah besar → candle kecil (bintang) → hijau besar yang ditutup di atas tengah candle merah pertama.",
    meaning: "Penurunan melemah (bintang = ragu), lalu pembeli mengambil alih.",
    tip: "Salah satu pola pembalikan paling andal, terutama di support kuat pada H1/H4.",
  },
  {
    name: "Evening Star",
    bias: "turun",
    candles: 3,
    bars: [
      [20, 52, 18, 50],
      [54, 62, 52, 57],
      [55, 56, 22, 24],
    ],
    look: "Hijau besar → candle kecil → merah besar yang ditutup di bawah tengah candle hijau pertama.",
    meaning: "Kenaikan kehabisan tenaga, lalu penjual mengambil alih.",
    tip: "Kebalikan Morning Star. Kuat di resistance dan bila RSI sebelumnya jenuh beli.",
  },
  {
    name: "Bullish Engulfing",
    bias: "naik",
    candles: 2,
    context: DOWN,
    bars: [
      [50, 52, 38, 40],
      [38, 62, 36, 60],
    ],
    look: "Candle hijau yang badannya 'menelan' seluruh badan candle merah sebelumnya.",
    meaning: "Pembeli langsung membalikkan seluruh penurunan candle sebelumnya.",
    tip: "Semakin besar candle hijau dibanding merah, semakin kuat.",
  },
  {
    name: "Bearish Engulfing",
    bias: "turun",
    candles: 2,
    context: UP,
    bars: [
      [44, 56, 42, 54],
      [56, 58, 36, 38],
    ],
    look: "Candle merah yang badannya menelan seluruh badan candle hijau sebelumnya.",
    meaning: "Penjual membalikkan seluruh kenaikan candle sebelumnya.",
    tip: "Kuat di resistance atau setelah kenaikan panjang.",
  },
  {
    name: "Piercing Line",
    bias: "naik",
    candles: 2,
    context: DOWN,
    bars: [
      [70, 72, 40, 42],
      [38, 64, 36, 62],
    ],
    look: "Merah besar, lalu hijau yang dibuka rendah dan ditutup di atas TENGAH badan merah.",
    meaning: "Pembeli merebut kembali lebih dari separuh penurunan.",
    tip: "Versi sedikit lebih lemah dari Bullish Engulfing.",
  },
  {
    name: "Dark Cloud Cover",
    bias: "turun",
    candles: 2,
    context: UP,
    bars: [
      [44, 64, 42, 62],
      [66, 67, 48, 50],
    ],
    look: "Hijau besar, lalu merah yang dibuka tinggi dan ditutup di bawah TENGAH badan hijau.",
    meaning: "Penjual merebut kembali lebih dari separuh kenaikan.",
    tip: "Kebalikan Piercing Line.",
  },
  {
    name: "Tweezer Bottom",
    bias: "naik",
    candles: 2,
    context: DOWN,
    bars: [
      [55, 57, 30, 34],
      [34, 58, 30, 55],
    ],
    look: "Dua candle dengan LOW hampir sama: merah lalu hijau.",
    meaning: "Harga dua kali gagal menembus level yang sama ke bawah → support.",
    tip: "Pasang SL sedikit di bawah low kembar tersebut.",
  },
  {
    name: "Tweezer Top",
    bias: "turun",
    candles: 2,
    context: UP,
    bars: [
      [44, 68, 42, 64],
      [64, 68, 44, 47],
    ],
    look: "Dua candle dengan HIGH hampir sama: hijau lalu merah.",
    meaning: "Harga dua kali gagal menembus level yang sama ke atas → resistance.",
    tip: "Pasang SL sedikit di atas high kembar tersebut.",
  },
  {
    name: "Three White Soldiers",
    bias: "naik",
    candles: 3,
    bars: [
      [20, 36, 18, 34],
      [32, 52, 30, 50],
      [48, 70, 46, 68],
    ],
    look: "Tiga candle hijau berturut-turut, badan besar, tiap close lebih tinggi, sumbu atas pendek.",
    meaning: "Tekanan beli kuat dan konsisten.",
    tip: "Jangan langsung kejar: sering ada koreksi dulu. Lebih baik tunggu pullback ke EMA20.",
  },
  {
    name: "Three Black Crows",
    bias: "turun",
    candles: 3,
    bars: [
      [80, 82, 64, 66],
      [68, 70, 48, 50],
      [52, 54, 30, 32],
    ],
    look: "Tiga candle merah berturut-turut, badan besar, tiap close lebih rendah.",
    meaning: "Tekanan jual kuat dan konsisten.",
    tip: "Sama seperti di atas: tunggu pantulan kecil sebelum ikut SELL.",
  },
  {
    name: "Spinning Top",
    bias: "ragu",
    candles: 1,
    bars: [[48, 70, 28, 52]],
    look: "Badan kecil di tengah, sumbu atas dan bawah sama-sama panjang.",
    meaning: "Pembeli dan penjual seimbang; pasar ragu-ragu.",
    tip: "Bukan sinyal arah. Di tengah tren bisa berarti tren melemah; tunggu candle berikutnya.",
  },
];

const BIAS_STYLE: Record<Bias, { label: string; className: string }> = {
  naik: { label: "▲ Potensi naik", className: "bg-buy/15 text-buy" },
  turun: { label: "▼ Potensi turun", className: "bg-sell/15 text-sell" },
  ragu: { label: "◆ Ragu-ragu", className: "bg-close/15 text-warn" },
};

// ---------- tata letak ----------

const SECTIONS = [
  { id: "aplikasi", title: "Cara memakai SignalFlow" },
  { id: "pola", title: "Pola candlestick" },
  { id: "indikator", title: "Indikator di grafik" },
  { id: "tips", title: "Tips analisa chart" },
  { id: "risiko", title: "Manajemen risiko" },
  { id: "kesalahan", title: "Kesalahan umum" },
  { id: "istilah", title: "Istilah" },
];

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section id={id} className="surface scroll-mt-20 space-y-3 rounded-2xl p-4">
      <h2 className="text-lg font-bold">{title}</h2>
      {children}
    </section>
  );
}

function Item({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <details className="group rounded-xl bg-panel-2 px-3 py-2.5">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-sm font-semibold">
        {title}
        <span className="text-muted transition group-open:rotate-90">›</span>
      </summary>
      <div className="mt-2 space-y-2 text-sm leading-relaxed text-fg-soft">{children}</div>
    </details>
  );
}

function Tag({ className, children }: { className: string; children: React.ReactNode }) {
  return <span className={`rounded-md px-1.5 py-0.5 text-xs font-bold ${className}`}>{children}</span>;
}

function PatternCards() {
  const [filter, setFilter] = useState<Bias | "semua">("semua");
  const shown = PATTERNS.filter((p) => filter === "semua" || p.bias === filter);
  return (
    <>
      <div className="flex flex-wrap gap-1.5">
        {(["semua", "naik", "turun", "ragu"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold capitalize ${
              filter === f ? "bg-brand/15 text-brand" : "bg-panel-2 text-muted"
            }`}
          >
            {f}
          </button>
        ))}
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {shown.map((p) => (
          <article key={p.name} className="space-y-2 rounded-xl bg-panel-2 p-3">
            <div className="flex items-start justify-between gap-2">
              <div>
                <h3 className="font-bold">{p.name}</h3>
                <p className="text-[11px] text-muted">{p.candles} candle</p>
              </div>
              <Tag className={BIAS_STYLE[p.bias].className}>{BIAS_STYLE[p.bias].label}</Tag>
            </div>
            <div className="flex justify-center rounded-lg bg-bg/60 py-1">
              <Candles context={p.context} bars={p.bars} />
            </div>
            <dl className="space-y-1 text-[13px] leading-snug">
              <div>
                <dt className="inline font-semibold">Bentuk: </dt>
                <dd className="inline text-fg-soft">{p.look}</dd>
              </div>
              <div>
                <dt className="inline font-semibold">Artinya: </dt>
                <dd className="inline text-fg-soft">{p.meaning}</dd>
              </div>
              <div>
                <dt className="inline font-semibold">Tips: </dt>
                <dd className="inline text-fg-soft">{p.tip}</dd>
              </div>
            </dl>
          </article>
        ))}
      </div>
    </>
  );
}

export default function GuidePage() {
  return (
    <>
      <AppHeader title="Panduan" subtitle="Belajar membaca sinyal & grafik" />
      <main className="mx-auto max-w-3xl space-y-4 px-4 py-4">
        <nav className="flex flex-wrap gap-1.5">
          {SECTIONS.map((s) => (
            <a key={s.id} href={`#${s.id}`} className="rounded-lg bg-panel-2 px-3 py-1.5 text-xs font-semibold text-fg-soft">
              {s.title}
            </a>
          ))}
        </nav>

        <Section id="aplikasi" title="Cara memakai SignalFlow">
          <p className="text-sm text-fg-soft">
            SignalFlow menganalisis grafik M15 setiap 15 menit dan menampilkan instruksi. Anda yang mengeksekusi order di
            aplikasi broker (FXTM / Olymp Trade) di HP.
          </p>
          <div className="grid gap-2 text-sm sm:grid-cols-2">
            <div className="rounded-xl bg-buy/10 p-3">
              <Tag className="bg-buy/20 text-buy">▲ BUY</Tag>
              <p className="mt-1.5 text-fg-soft">Buka posisi beli. Untung bila harga naik.</p>
            </div>
            <div className="rounded-xl bg-sell/10 p-3">
              <Tag className="bg-sell/20 text-sell">▼ SELL</Tag>
              <p className="mt-1.5 text-fg-soft">Buka posisi jual. Untung bila harga turun.</p>
            </div>
            <div className="rounded-xl bg-close/10 p-3">
              <Tag className="bg-close/20 text-warn">■ CLOSE</Tag>
              <p className="mt-1.5 text-fg-soft">Tutup posisi yang sedang terbuka sekarang (kondisi berubah / batas waktu).</p>
            </div>
            <div className="rounded-xl bg-panel-2 p-3">
              <Tag className="bg-wait/20 text-muted">WAIT</Tag>
              <p className="mt-1.5 text-fg-soft">Belum ada setup. Jangan buka posisi; tidak trading juga keputusan yang benar.</p>
            </div>
          </div>
          <Item title="Entry, Stop Loss (SL), Take Profit (TP)">
            <p>
              <b>Entry</b> = harga masuk. <b>SL</b> = batas rugi; posisi otomatis ditutup bila harga melawan sampai titik
              ini. <b>TP</b> = target untung.
            </p>
            <p>
              Pasang SL dan TP <b>saat membuka order</b> di broker, jangan menunggu. Jangan menggeser SL menjauh ketika
              harga mendekatinya.
            </p>
          </Item>
          <Item title="Sinyal kedaluwarsa">
            <p>
              Sinyal hanya layak dimasuki dalam ±45 menit setelah muncul dan selama harga belum terlalu jauh dari entry.
              Bila tertulis <i>kedaluwarsa</i>, jangan masuk. Bila sudah terlanjur masuk, biarkan SL/TP bekerja.
            </p>
          </Item>
          <Item title="Status uji strategi (hijau / kuning / abu-abu)">
            <p>
              <b className="text-ok">✓ Hijau</b>: strategi lolos uji backtest 2 tahun (bukan jaminan untung).{" "}
              <b className="text-warn">⚠ Kuning</b>: sinyal tetap tampil tetapi belum terbukti menguntungkan — pakai akun
              demo / lot kecil. <b>⏸ Abu-abu</b>: sinyal dimatikan, grafik tetap bisa dipantau.
            </p>
          </Item>
          <Item title="Analisis AI">
            <p>
              Tombol <b>Analisis AI</b> meminta AI membaca fakta grafik (tren, indikator, pola) dan memberi saran. AI
              bersifat eksperimen: keyakinan AI adalah perkiraan AI sendiri, belum teruji. Untuk XAUUSD, uji historis
              menunjukkan AI lebih sering salah.
            </p>
          </Item>
          <Item title="Kalibrasi harga & ukuran lot">
            <p>
              Harga data bisa sedikit berbeda dengan harga di broker. Di <Link className="text-brand underline" href="/settings">Pengaturan</Link>,
              masukkan harga BID broker untuk kalibrasi, lalu isi modal dan % risiko agar aplikasi menghitung saran lot.
            </p>
          </Item>
        </Section>

        <Section id="pola" title="Pola candlestick">
          <Item title="Membaca satu candle">
            <div className="flex items-center gap-3">
              <Candles bars={[[30, 85, 15, 70]]} />
              <p>
                <b>Badan</b> = jarak open–close (hijau: close &gt; open, harga naik; merah: turun). <b>Sumbu/ekor</b> = harga
                tertinggi dan terendah yang sempat dicapai. Sumbu panjang = harga sempat ke sana tetapi ditolak.
              </p>
            </div>
          </Item>
          <Item title="Cara aplikasi menilai kekuatan pola (●●●)">
            <p>
              ● dasar: pola terbentuk. ●● +1 bila muncul di area support/resistance (Bollinger luar, swing high/low 20
              candle, atau EMA50). ●●● +1 lagi bila searah tren. Di grafik, tombol <b>POLA</b> menampilkan pola kuat (★).
            </p>
            <p>
              Uji 2 tahun: pola candlestick <b>saja</b> tidak menguntungkan sebagai pemicu entry. Gunakan sebagai
              konfirmasi tambahan, bukan alasan utama.
            </p>
          </Item>
          <PatternCards />
        </Section>

        <Section id="indikator" title="Indikator di grafik">
          <Item title="EMA 20 / 50 / 200 (garis rata-rata)">
            <p>
              Harga di atas EMA50 dan EMA50 di atas EMA200 = <b>tren naik</b>; kebalikannya tren turun. EMA20 sering
              menjadi tempat harga &quot;beristirahat&quot; (pullback) sebelum melanjutkan tren.
            </p>
          </Item>
          <Item title="RSI (kekuatan gerak, 0–100)">
            <p>
              Di atas 70 = jenuh beli (rawan koreksi turun), di bawah 30 = jenuh jual. Dalam tren kuat RSI bisa lama di
              zona ekstrem, jadi jangan SELL hanya karena RSI 70.
            </p>
          </Item>
          <Item title="MACD (momentum)">
            <p>
              Histogram positif dan membesar = momentum naik menguat. Histogram berganti tanda = momentum berbalik. Cocok
              untuk melihat apakah tren mulai melemah.
            </p>
          </Item>
          <Item title="Bollinger Bands (pita volatilitas)">
            <p>
              Harga menyentuh pita atas/bawah = relatif mahal/murah terhadap rata-rata 20 candle. Pita menyempit = pasar
              tenang, sering diikuti pergerakan besar.
            </p>
          </Item>
          <Item title="ADX & ATR">
            <p>
              <b>ADX</b> mengukur kekuatan tren (bukan arah): &gt; 25 tren kuat, &lt; 20 pasar mendatar. <b>ATR</b> =
              rata-rata jarak gerak per candle; aplikasi memakainya untuk jarak SL agar sesuai volatilitas.
            </p>
          </Item>
        </Section>

        <Section id="tips" title="Tips analisa chart">
          <ol className="list-decimal space-y-2 pl-5 text-sm leading-relaxed text-fg-soft">
            <li>
              <b>Mulai dari timeframe besar.</b> Lihat H4 → H1 untuk arah tren, baru M15 untuk waktu masuk. Ikuti arah tren
              besar; melawan tren peluangnya lebih kecil.
            </li>
            <li>
              <b>Tandai support & resistance.</b> Area di mana harga berkali-kali berbalik (swing high/low). Pola di area
              ini jauh lebih bermakna daripada di tengah-tengah.
            </li>
            <li>
              <b>Tunggu candle tutup.</b> Pola belum sah sebelum candle selesai; Hammer bisa berubah bentuk di detik
              terakhir.
            </li>
            <li>
              <b>Cari konfirmasi, bukan satu alasan.</b> Contoh BUY yang baik: tren H1 naik + harga pullback ke EMA20/support
              + Hammer/Bullish Engulfing + RSI keluar dari zona bawah.
            </li>
            <li>
              <b>Jangan kejar harga.</b> Bila harga sudah lari jauh dari entry (sinyal kedaluwarsa), lewatkan. Akan ada
              kesempatan lain.
            </li>
            <li>
              <b>Perhatikan jam pasar (WIB).</b> Asia ±05:00–14:00 (cenderung sepi, rentang sempit), London ±14:00–23:00,
              New York ±19:00–04:00. Tumpang tindih London–NY (±19:00–23:00) paling ramai. Jam bergeser ±1 jam saat
              pergantian musim panas/dingin di Eropa/AS.
            </li>
            <li>
              <b>Hindari berita besar.</b> Data seperti NFP, CPI, atau keputusan suku bunga bisa membuat harga melompat
              melewati SL. Aplikasi menahan sinyal di sekitar berita yang terdaftar.
            </li>
            <li>
              <b>Pasar sepi atau terlalu liar = tunggu.</b> Candle sangat kecil (pasar mati) atau sangat besar (lonjakan)
              membuat sinyal tidak dapat diandalkan.
            </li>
          </ol>
        </Section>

        <Section id="risiko" title="Manajemen risiko">
          <ul className="list-disc space-y-2 pl-5 text-sm leading-relaxed text-fg-soft">
            <li>
              <b>Risiko 1–2% per trade.</b> Dengan modal $1.000 dan risiko 1%, kerugian maksimal per trade $10.
            </li>
            <li>
              <b>Hitung lot dari jarak SL.</b> Contoh EURUSD: SL 20 pip, 1 lot = $10/pip → lot = $10 ÷ (20 × $10) = 0,05
              lot. Aplikasi menghitungnya otomatis bila modal diisi.
            </li>
            <li>
              <b>Risk:Reward minimal 1:2.</b> Dengan R:R 1:2, menang 34% saja sudah impas. Karena itu win rate 40–45% masih
              bisa untung.
            </li>
            <li>
              <b>Kekalahan beruntun itu normal.</b> Strategi yang lolos uji pun bisa kalah 5–8 kali berturut-turut. Jangan
              menaikkan lot untuk &quot;balas dendam&quot;.
            </li>
            <li>
              <b>Batas rugi harian.</b> Misalnya berhenti trading hari itu setelah rugi 3%.
            </li>
            <li>
              <b>Mulai di akun demo.</b> Ikuti sinyal di demo minimal beberapa minggu dan catat hasilnya sebelum memakai
              uang sungguhan.
            </li>
          </ul>
        </Section>

        <Section id="kesalahan" title="Kesalahan umum">
          <ul className="list-disc space-y-2 pl-5 text-sm leading-relaxed text-fg-soft">
            <li>Tidak memasang SL, atau menggeser SL menjauh karena berharap harga berbalik.</li>
            <li>Menutup posisi untung terlalu cepat tetapi membiarkan posisi rugi terlalu lama.</li>
            <li>Masuk karena satu pola saja tanpa melihat tren dan support/resistance.</li>
            <li>Memaksa trading saat status WAIT karena bosan.</li>
            <li>Lot terlalu besar dibanding modal sehingga beberapa kekalahan menghabiskan akun.</li>
            <li>Mengabaikan spread: di jam sepi atau saat berita, spread broker bisa melebar.</li>
          </ul>
        </Section>

        <Section id="istilah" title="Istilah">
          <dl className="grid gap-2 text-sm sm:grid-cols-2">
            {[
              ["Pip", "Satuan gerak harga terkecil yang umum. EURUSD 0,0001; USDJPY 0,01."],
              ["Spread", "Selisih harga beli (ask) dan jual (bid) — biaya setiap order."],
              ["Lot", "Ukuran posisi. 1 lot standar = 100.000 unit mata uang dasar."],
              ["R", "Satu kali jarak risiko (entry→SL). Untung 2R = dua kali risiko."],
              ["Win rate", "Persentase trade yang untung."],
              ["Profit factor (PF)", "Total untung ÷ total rugi. Di atas 1 = untung bersih."],
              ["Drawdown", "Penurunan modal terbesar dari puncak sebelumnya."],
              ["Backtest", "Menguji strategi pada data harga masa lalu."],
              ["In-sample / out-of-sample", "Data untuk memilih strategi / data terpisah untuk mengujinya secara jujur."],
              ["Pullback", "Koreksi sementara melawan arah tren sebelum tren berlanjut."],
              ["Breakout", "Harga menembus batas rentang (high/low) sebelumnya."],
              ["Timeframe", "Durasi satu candle: M15 = 15 menit, H1 = 1 jam, H4 = 4 jam."],
            ].map(([term, def]) => (
              <div key={term} className="rounded-xl bg-panel-2 p-2.5">
                <dt className="font-semibold">{term}</dt>
                <dd className="text-[13px] text-fg-soft">{def}</dd>
              </div>
            ))}
          </dl>
        </Section>

        <Disclaimer />
      </main>
    </>
  );
}
