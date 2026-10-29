# SignalFlow

Dashboard **sinyal trading** M15 untuk XAUUSD, EURUSD, GBPUSD, USDJPY (dan instrumen lain lewat
konfigurasi). Menampilkan sinyal **BUY / SELL / CLOSE / WAIT** lengkap dengan entry, stop loss,
take profit, tingkat keyakinan, dan alasan dalam bahasa Indonesia.

SignalFlow **hanya menampilkan sinyal**. Tidak ada eksekusi order otomatis dan tidak ada koneksi
ke akun broker. Anda membuka dashboard di HP lalu mengeksekusi sendiri di aplikasi broker
(misalnya Olymp Trade mode Forex atau FXTM Trader).

> ⚠️ **Disclaimer:** sinyal dari aplikasi ini bukan saran keuangan. Trading forex dan emas
> berisiko tinggi. Gunakan akun demo terlebih dahulu.

## Arsitektur

| Service    | Teknologi                          | Port bawaan | Fungsi                                  |
|------------|------------------------------------|-------------|-----------------------------------------|
| `proxy`    | Caddy 2                            | 8080        | Pintu masuk tunggal: `/` dashboard, `/api` backend, `/ws` WebSocket |
| `backend`  | Python 3.12, FastAPI               | 8000        | REST API, WebSocket, migrasi database   |
| `worker`   | Python 3.12, APScheduler           | –           | Analisis tiap :00/:15/:30/:45 WIB       |
| `frontend` | Next.js 15, TypeScript, Tailwind   | (internal)  | Dashboard mobile-first (PWA)            |
| `postgres` | PostgreSQL 16                      | 5432*       | Candle, sinyal, kalibrasi, backtest     |
| `redis`    | Redis 7                            | 6379*       | Cache, lock, pub/sub sinyal real-time   |

\* hanya terbuka di `127.0.0.1`. Port bisa diubah lewat `APP_PORT`, `BACKEND_PORT`,
`POSTGRES_PORT`, dan `REDIS_PORT` di `.env`.

```
SignalFlow/
├── backend/            # FastAPI + worker (satu image Docker)
│   ├── app/
│   │   ├── api/        # router REST/WebSocket
│   │   ├── core/       # config, logging, instrumen, timeframe, redis
│   │   ├── db/         # SQLAlchemy model & session
│   │   └── worker/     # scheduler M15
│   ├── alembic/        # migrasi database
│   └── tests/          # pytest
├── frontend/           # Next.js dashboard (PWA)
├── proxy/Caddyfile     # reverse proxy
├── config/
│   ├── instruments.yaml  # daftar instrumen (bisa ditambah)
│   ├── strategies.yaml   # strategi aktif & parameternya
│   └── news_events.yaml  # kalender berita manual
├── docker-compose.yml
└── .env.example
```

## Cara menjalankan

Prasyarat: Docker Desktop (Windows/macOS) atau Docker Engine + Compose v2 (Linux).
Semua perintah di bawah dijalankan dari folder proyek (yang berisi `docker-compose.yml`).

### Pertama kali (setup)

```bash
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env
# edit .env: isi POSTGRES_PASSWORD, TWELVEDATA_API_KEY, (opsional) GROQ_API_KEY
docker compose up -d --build  # build image + jalankan semua service (pertama kali bisa 5–15 menit)
docker compose ps             # tunggu sampai backend berstatus "healthy"
```

Migrasi database dijalankan otomatis oleh service `backend` setiap kali start.

- Dashboard: http://localhost:8080 (atau `APP_PORT` Anda)
- Dokumentasi API (Swagger): http://localhost:8000/docs
- Status sistem: http://localhost:8080/api/health

Jika port 8080/8000 sudah dipakai aplikasi lain, ubah `APP_PORT` / `BACKEND_PORT` di `.env`
lalu `docker compose up -d`.

### Pemakaian sehari-hari

1. Pastikan **Docker Desktop sudah berjalan** (ikon paus di menu bar/taskbar). Bila belum,
   buka aplikasinya; di macOS bisa `open -a Docker`. Error `Cannot connect to the Docker
   daemon` berarti Docker Desktop belum menyala.
2. Jalankan:

```bash
docker compose up -d          # start (tanpa build ulang, cepat)
docker compose ps             # cek status semua service
docker compose stop           # hentikan sementara (data tetap aman)
docker compose down           # hentikan & hapus container (data di volume tetap aman)
```

Semua service memakai `restart: unless-stopped`, jadi otomatis hidup lagi setiap Docker
Desktop dibuka, kecuali terakhir dihentikan dengan `stop`/`down`.

### Setelah mengubah sesuatu

| Yang diubah | Perintah |
|---|---|
| `.env` | `docker compose up -d` (container yang terdampak dibuat ulang) |
| `config/*.yaml` | `docker compose restart backend worker` (`news_events.yaml` tanpa restart) |
| Kode `backend/` atau `requirements.txt` | `docker compose up -d --build backend worker` |
| Kode `frontend/` | `docker compose up -d --build frontend` |
| `streamer/bridge.mjs` | `docker compose restart streamer` |
| `proxy/Caddyfile` | `docker compose restart proxy` |
| Setelah `git pull` | `docker compose up -d --build` |

### Log & pemecahan masalah

```bash
docker compose logs -f backend          # log satu service (backend/worker/frontend/streamer/proxy)
docker compose logs --tail=100 worker   # 100 baris terakhir
docker compose exec backend sh          # masuk ke container backend
docker compose exec postgres psql -U signalflow   # konsol database
```

- **Backend tidak healthy / restart terus**: lihat `docker compose logs backend`. Biasanya
  `.env` belum lengkap (mis. `POSTGRES_PASSWORD` kosong) atau migrasi gagal.
- **Port sudah dipakai** (`Ports are not available` / `address already in use`): ubah port
  yang bentrok di `.env`. Bila Postgres/Redis lokal (mis. Homebrew) sudah memakai 5432/6379,
  set `POSTGRES_PORT=5433` dan `REDIS_PORT=6380`. Cek pemakai port: `lsof -nP -iTCP:5432 -sTCP:LISTEN`.
- **`network signalflow_default ... incorrect label`**: sisa network dari versi Compose lama.
  Jalankan `docker compose down` (atau `docker network rm signalflow_default`) lalu `up -d` lagi.
- **Grafik tidak bergerak**: cek `docker compose logs streamer` dan `TWELVEDATA_API_KEY`.
- **Mengganti `POSTGRES_PASSWORD` setelah database dibuat** tidak berpengaruh; password
  hanya dipakai saat volume pertama kali dibuat (lihat reset di bawah).

### Reset total (hapus semua data)

> ⚠️ Menghapus seluruh candle, sinyal, kalibrasi, dan pengaturan. Tidak bisa dibatalkan.

```bash
docker compose down -v        # -v ikut menghapus volume pgdata & redisdata
docker compose up -d --build
```

### Membuka dari iPhone (Wi-Fi yang sama)

1. Cari IP laptop: PowerShell `ipconfig` → "IPv4 Address" (mis. `192.168.1.20`);
   di macOS `ipconfig getifaddr en0`.
2. Di Safari iPhone buka `http://192.168.1.20:8080`.
3. Bila tidak terbuka, izinkan port di Windows Firewall (PowerShell sebagai Administrator):
   `New-NetFirewallRule -DisplayName SignalFlow -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow`
4. Safari → Bagikan → **Tambah ke Layar Utama** untuk memasangnya seperti aplikasi.

> SignalFlow tidak mengirim notifikasi apa pun; buka dashboard saat ingin trading. Aktifkan
> "Layar tetap menyala" di beranda agar layar HP tidak mati saat memantau.

## Dashboard

- **Grafik** (layar utama), dipantau sambil trading di aplikasi broker:
  - Tab instrumen di atas dengan lencana aksi berwarna (BUY hijau, SELL merah, CLOSE kuning,
    WAIT abu-abu), sehingga sinyal di pair lain tetap terlihat.
  - Bilah instruksi tepat di atas grafik: "BUY sekarang · Entry · SL · TP · lot",
    "SELL kedaluwarsa, jangan masuk", "Tutup posisi BUY sekarang", atau "Tunggu, jangan
    buka posisi". Bilah berkedip saat ada sinyal baru.
  - Candlestick M1/M5/M15/H1/H4 dengan EMA 20/50/200, Bollinger Bands, panel RSI & MACD,
    panah BUY/SELL/CLOSE, garis Entry/SL/TP, live candle, waktu WIB, cubit untuk zoom.
  - Kartu detail di bawah grafik: jarak SL/TP dalam pip, status, saran lot, alasan.
  - **🧠 Analisis AI**: AI Groq hanya bekerja saat tombol ditekan, untuk instrumen yang sedang
    dibuka → BUY / SELL / WAIT (atau tahan / CLOSE bila ada posisi AI aktif). Jeda 45 detik
    antar analisis; TP/SL posisi AI tetap dipantau otomatis tanpa memakai kuota AI.
  - Hanya instrumen yang sedang dibuka yang dianalisis; tab lain "tidak dipantau".
  - Semuanya diperbarui otomatis tiap candle M15 tutup, tanpa perlu refresh.
- **Riwayat**: statistik sinyal live + semua sinyal beserta status & hasil pip.
- **Backtest**: uji strategi pada data historis (lihat di bawah).
- **Tema gelap / terang / ikuti sistem**: tombol ☀/☾ di kanan atas atau Pengaturan → Tampilan
  (disimpan per perangkat; grafik ikut berganti warna).
- **Pengaturan**: modal & % risiko, kalibrasi harga & spread per instrumen, panduan pasang
  di iPhone, status sistem.

### Mengisi API key Twelve Data

1. Daftar gratis di https://twelvedata.com/ lalu buka menu **API Keys**.
2. Salin key ke `.env` → `TWELVEDATA_API_KEY=...`
3. Paket gratis: 8 request/menit dan 800/hari. Aplikasi memakai cache dan hanya mengambil
   H1/H4 saat candle-nya baru tutup; M1/M5 hanya diambil ketika grafiknya dibuka.
4. Restart: `docker compose restart backend worker`

### Mencoba tanpa API key (data sintetis)

Set `DATA_PROVIDER=mock` di `.env` lalu `docker compose up -d`. Provider `mock` menghasilkan
candle sintetis yang konsisten, sehingga seluruh aplikasi bisa diuji tanpa kuota. Ganti
kembali ke `twelvedata` setelah API key diisi, lalu hapus data sintetis:

```bash
docker compose exec postgres psql -U signalflow -c "DELETE FROM candles WHERE source='mock';"
docker compose restart backend worker
```

### Grafik real-time (live candle)

- **Real-time tiap ±1 detik** untuk simbol yang diizinkan paket Twelve Data. Paket gratis saat
  ini: **XAUUSD dan EURUSD** (lencana hijau **LIVE** di grafik). Service `streamer`
  ([streamer/bridge.mjs](streamer/bridge.mjs), Node tanpa dependensi) memegang koneksi
  WebSocket Twelve Data dan meneruskan harga ke Redis; worker membentuk candle berjalan
  M1–H4 dan dashboard menerimanya lewat `/ws`. Tidak memakai kuota REST. Bila paket
  dinaikkan, simbol lain otomatis ikut streaming. Matikan dengan `TWELVEDATA_STREAMING=false`.
- **Simbol lain (GBPUSD, USDJPY di paket gratis)**: candle berjalan diperbarui setiap
  `LIVE_REFRESH_SECONDS` (bawaan 60 detik = 1 request/menit) lewat REST, hanya saat grafiknya dibuka. Bila sisa
  kuota harian ≤ `TWELVEDATA_RESERVED_DAILY` (bawaan 300), pembaruan ini dijeda agar
  analisis sinyal M15 tetap mendapat data.

> Keputusan sinyal hanya memakai candle yang **sudah tutup**; harga real-time hanya untuk
> tampilan grafik, harga terkini, dan status "kedaluwarsa, jangan masuk".

### Kalibrasi harga ke broker

Harga feed (Twelve Data) bisa sedikit berbeda dari harga di aplikasi broker Anda. Kalibrasi
menghitung selisihnya (offset) per instrumen, lalu semua harga grafik dan sinyal ditampilkan
dalam versi "disesuaikan ke broker".

1. Buka aplikasi broker, lihat harga **Sell/Bid** instrumen (mis. XAUUSD).
2. Segera masukkan angka itu ke dashboard (atau via API di bawah). Sistem mengambil harga feed
   pada detik yang sama lalu menyimpan `offset = harga broker − harga feed`.
3. Lakukan saat pasar tenang (bukan saat rilis berita) agar selisih waktu input tidak berpengaruh.
   Ulangi sesekali, misalnya tiap minggu; waktu kalibrasi terakhir selalu ditampilkan.

```bash
curl -X POST localhost:8000/instruments/XAUUSD/calibrate \
     -H "content-type: application/json" -d '{"broker_price": 4012.35}'
curl -X PUT localhost:8000/instruments/XAUUSD/settings \
     -H "content-type: application/json" -d '{"spread_pips": 3.0}'   # spread manual
curl -X DELETE localhost:8000/instruments/XAUUSD/calibration           # reset offset
```

Selisih di atas 2% ditolak karena hampir pasti salah ketik atau salah instrumen.

## Cara kerja sinyal

Setiap :00/:15/:30/:45 WIB (+10 detik) worker menyinkronkan candle lalu menganalisis tiap
instrumen dengan strategi aktif di [config/strategies.yaml](config/strategies.yaml).

| Aksi  | Kapan muncul |
|-------|--------------|
| BUY   | Tren H1 & H4 naik (harga & EMA50 di atas EMA200, ADX ≥ 20) + di M15 harga pullback ke EMA20 lalu ditutup di atasnya, plus RSI keluar dari zona jenuh jual (naik melewati 40) dan/atau MACD cross naik |
| SELL  | Kebalikan BUY |
| CLOSE | Sinyal aktif kena SL / trailing stop, sinyal berbalik arah, momentum melemah (histogram MACD berbalik + harga menembus EMA20, atau tren H1 berbalik), atau sudah 8 jam |
| WAIT  | Tidak ada setup valid (alasannya selalu ditampilkan) |

- **SL** = 1.5 × ATR(14), **TP** = 3 × ATR, dan TP dilebarkan otomatis agar R:R tetap
  minimal 1:2 **setelah spread**.
- **Trailing stop** (BUY & SELL, termasuk sinyal AI / AI semua): setelah untung 1R
  (R = jarak SL awal), SL mengikuti harga terbaik sejak entry sejauh 0.5R, sehingga
  keuntungan terkunci dan posisi ditutup dekat puncaknya. TP dilepas (`take_profit: false`).
  Saat SL bergeser, dashboard menampilkan **"geser SL ke …"**: geser SL di aplikasi broker
  dan jangan pasang TP. Atur di `trailing_stop` pada
  [config/strategies.yaml](config/strategies.yaml). Backtest strategi aktif (EURUSD/USDJPY,
  out-of-sample): +10.2R → +21.7R, drawdown 6.9R → 5.0R.
- **Filter** (sinyal ditahan → WAIT): volatilitas ekstrem/terlalu sepi, candle lonjakan,
  45 menit sebelum pasar tutup Jumat, dan ±30 menit dari berita besar di
  [config/news_events.yaml](config/news_events.yaml) (bisa diedit tanpa restart).
- **Keyakinan**: rendah / sedang / tinggi dari jumlah pemicu, kekuatan ADX, susunan EMA,
  arah candle, dan posisi RSI.
- **Alasan** dalam bahasa Indonesia selalu dibuat dari aturan. Bila `GROQ_API_KEY` diisi,
  Groq (`GROQ_MODEL`, bawaan `openai/gpt-oss-120b`) merangkainya menjadi kalimat yang lebih
  natural. LLM tidak menentukan sinyal maupun angka, dan bila gagal teks aturan yang dipakai.
- Sinyal hanya disarankan untuk dimasuki 45 menit setelah muncul (`entry_valid_minutes`).

### Menambah strategi sendiri

1. Buat `backend/app/strategies/nama_strategi.py`, turunkan kelas `Strategy`, beri `@register`.
2. Impor modulnya di `backend/app/strategies/__init__.py`.
3. Set `active: nama_strategi` di `config/strategies.yaml`, lalu `docker compose up -d --build worker`.

```bash
docker compose exec backend python -m app.cli analyze          # analisis sekarang juga
docker compose exec backend python -m app.cli scan --days 30   # replay strategi di data tersimpan
curl localhost:8000/analysis/latest                            # BUY/SELL/CLOSE/WAIT per instrumen
curl "localhost:8000/signals?symbol=XAUUSD"                    # riwayat sinyal
```

## API

Dokumentasi interaktif: http://localhost:8000/docs

| Endpoint | Fungsi |
|----------|--------|
| `GET /dashboard` | Kartu semua instrumen (aksi, sinyal, harga, status entry, lot) + waktu candle berikutnya |
| `GET /signals/latest?symbol=XAUUSD` | Kartu satu instrumen |
| `GET /signals?symbol=&action=&status=&before_id=&limit=` | Riwayat sinyal (alias `/signals/history`) |
| `GET /signals/{id}` | Detail satu sinyal |
| `GET/PUT /settings/risk` | Modal (USD) & % risiko untuk saran lot, misalnya `{"capital": 1000, "risk_percent": 1}` |
| `GET /instruments`, `PUT /instruments/{sym}/settings`, `POST /instruments/{sym}/calibrate` | Spread & kalibrasi |
| `GET /candles?symbol=&timeframe=M1\|M5\|M15\|H1\|H4` | Candle untuk grafik + live candle |
| `WS /ws` | Real-time: `card` tiap analisis, `signal` saat BUY/SELL/CLOSE baru, `live` candle berjalan |

Setiap sinyal di kartu berisi:
- Harga entry/SL/TP yang **sudah disesuaikan ke broker** (offset kalibrasi saat ini), plus
  jarak SL/TP dalam pip, sehingga tetap bisa dipakai walau harga broker sedikit berbeda.
- `status_label`: aktif · kedaluwarsa · kena TP · kena SL · ditutup.
- `entry_state_label`: "kedaluwarsa, jangan masuk" bila sinyal sudah lewat 45 menit
  (`entry_valid_minutes`) atau harga bergerak lebih dari `signal_validity_pips` dari entry.
  Sinyal kedaluwarsa tetap dipantau sampai TP/SL/CLOSE untuk yang sudah terlanjur masuk.
- `suggested_lot`: lot agar kerugian saat kena SL ≈ modal × % risiko (dibulatkan ke bawah
  ke 0.01, akun USD). Bila 0.0, modal terlalu kecil untuk SL tersebut.

Harga terkini di kartu memakai live candle bila grafik instrumen itu sedang dibuka
(`price_source: live`); selain itu memakai penutupan M15 terakhir (`last_close`) agar
kuota API tidak habis.

WebSocket (contoh di konsol browser):
```js
const ws = new WebSocket("ws://localhost:8000/ws");
ws.onmessage = (e) => console.log(JSON.parse(e.data));
ws.onopen = () => ws.send(JSON.stringify({ action: "subscribe_live", symbol: "XAUUSD", timeframe: "M15" }));
```

### Data historis (untuk backtest)

```bash
docker compose exec backend python -m app.cli price                     # cek koneksi provider
docker compose exec backend python -m app.cli sync                      # sinkron M15/H1/H4 sekarang
docker compose exec backend python -m app.cli backfill --timeframe H4 --days 400
docker compose exec backend python -m app.cli backfill --timeframe H1 --days 400
docker compose exec backend python -m app.cli backfill --timeframe M15 --days 370
docker compose exec backend python -m app.cli prune                     # buang candle saat pasar tutup
```

Backfill 1 tahun M15 memakan sekitar 8 request per instrumen. Twelve Data juga mengirim
candle akhir pekan; sinkronisasi otomatis membuangnya, dan `prune` membersihkan yang
terlanjur tersimpan.

## Backtest & statistik

Halaman **Backtest** di dashboard (atau `python -m app.cli backtest --days 365`) menguji
strategi aktif pada candle historis dengan logika yang **sama persis** dengan sinyal live.

- **Biaya**: spread per instrumen (atau spread manual di Pengaturan) + `slippage_pips`
  saat masuk dan keluar.
- **Metrik**: jumlah trade, win rate, profit factor, total R & pip, expectancy, rata-rata
  R:R (rencana vs realisasi), max drawdown (R dan % dengan risiko tetap per sinyal), Sharpe.
  R = kelipatan risiko; +2R berarti untung 2× jarak SL.
- **Anti-overfitting**: 70% periode awal = in-sample, 30% akhir = out-of-sample, ditambah
  4 periode berurutan untuk melihat konsistensi. Opsi *optimasi* mencoba kombinasi
  `sl_atr`, `tp_atr`, `min_triggers`, memilih yang terbaik **hanya** dari in-sample, lalu
  menampilkan hasilnya di out-of-sample. Strategi yang bagus di in-sample tapi buruk di
  out-of-sample berarti overfitting.
- Tidak termasuk: filter berita (tidak ada histori kalender), swap/biaya inap.

Halaman **Riwayat** menampilkan statistik yang sama untuk sinyal **live** yang sudah selesai
(7/30/90/365 hari terakhir).

### Riset & pemilihan strategi per instrumen

`python -m app.cli research --days 365` menguji 8 kandidat strategi per instrumen dengan aturan
di [backend/app/backtest/validation.py](backend/app/backtest/validation.py):

1. Kandidat dipilih **hanya dari in-sample** (expectancy tertinggi, minimal 40 trade).
2. Lolos bila in-sample tidak rugi (PF ≥ 1.0) **dan** out-of-sample PF ≥ 1.1, expectancy > 0,
   minimal 20 trade.
3. Instrumen tanpa kandidat yang lolos memakai strategi `disabled` (selalu WAIT).

Hasil riset pertama (data Okt 2025–Okt 2026) yang kini terpasang di
[config/strategies.yaml](config/strategies.yaml):

| Instrumen | Strategi | In-sample | Out-of-sample | Status |
|---|---|---|---|---|
| EURUSD | breakout sesi Asia + tren H4 | PF 1.19 (43 trade) | PF 1.36 (26 trade) | lolos |
| USDJPY | breakout sesi Asia | PF 1.10 (85 trade) | PF 1.26 (46 trade) | lolos |
| GBPUSD | — | terbaik rugi (PF 0.83) | — | dinonaktifkan |
| XAUUSD | — | PF 1.08 | PF 0.90 | dinonaktifkan |

Strategi bawaan lama (`trend_pullback`) rugi di keempat instrumen (PF 0.74, −155R).

> "Lolos" berarti positif di data yang belum pernah dipakai memilih strategi, **bukan
> jaminan profit**: jumlah trade out-of-sample masih kecil (26–46) dan 32 kombinasi diuji,
> sehingga sebagian keberhasilan bisa kebetulan. Pantau dulu di **akun demo** dan
> bandingkan dengan statistik sinyal live di halaman Riwayat. Di grafik, setiap instrumen
> menampilkan status validasinya (lolos / belum terbukti / dinonaktifkan).

### Menambah instrumen

Tambahkan entri di [config/instruments.yaml](config/instruments.yaml), lalu
`docker compose restart backend worker`.

## Pengujian

```bash
docker compose run --rm --no-deps backend pytest -q     # unit test backend
docker compose run --rm --no-deps backend ruff check .  # lint
docker compose logs -f worker                           # pantau siklus scheduler
```

## Status pengerjaan

- [x] Tahap 1 — Struktur proyek, docker-compose, .env.example
- [x] Tahap 2 — Data provider, penyimpanan candle, kalibrasi offset, live candle
- [x] Tahap 3 — Indikator, mesin sinyal, scheduler 15 menit, alasan AI (Groq)
- [x] Tahap 4 — API + WebSocket
- [x] Tahap 5 — Dashboard Next.js (kartu sinyal + grafik) sebagai PWA
- [–] Tahap 6 — Notifikasi (dibatalkan: aplikasi murni tampilan, tanpa notifikasi)
- [x] Tahap 7 — Riwayat, statistik, dan backtest
