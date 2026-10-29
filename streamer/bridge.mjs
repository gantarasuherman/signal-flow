// Jembatan streaming harga Twelve Data → Redis (Node 22, tanpa dependensi npm).
//
// Klien WebSocket Python tidak bisa menyelesaikan handshake ke ws.twelvedata.com, sedangkan
// klien WebSocket bawaan Node bisa, jadi koneksi streaming dipegang service kecil ini.
// Ia hanya meneruskan harga mentah; pembentukan candle dilakukan worker Python
// (app/data/stream.py) yang berlangganan channel `ticks:raw`.
//
//   Redis GET  stream:wanted  → ["XAU/USD", "EUR/USD", ...]  (ditulis worker saat start)
//   Redis PUBLISH ticks:raw   ← {"symbol": "XAU/USD", "price": 4040.5}
//   Redis SET  stream:status  ← {"success": [...], "fails": [...]}

import net from "node:net";

const API_KEY = process.env.TWELVEDATA_API_KEY ?? "";
const REDIS_HOST = process.env.REDIS_HOST ?? "redis";
const REDIS_PORT = Number(process.env.REDIS_PORT ?? 6379);
const URL = "wss://ws.twelvedata.com/v1/quotes/price?apikey=";
const HEARTBEAT_MS = 10_000;
const MAX_BACKOFF_MS = 300_000;

const log = (...args) => console.log(new Date().toISOString(), "|", ...args);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- Klien Redis minimal (protokol RESP) ----------

function encode(args) {
  let out = `*${args.length}\r\n`;
  for (const a of args) out += `$${Buffer.byteLength(a)}\r\n${a}\r\n`;
  return out;
}

/** Satu perintah di koneksi sementara; mengembalikan bulk string (atau null). */
function redisOnce(args) {
  return new Promise((resolve, reject) => {
    const sock = net.createConnection(REDIS_PORT, REDIS_HOST);
    let buf = "";
    sock.setTimeout(5000, () => sock.destroy(new Error("Redis timeout")));
    sock.on("connect", () => sock.write(encode(args)));
    sock.on("data", (chunk) => {
      buf += chunk.toString();
      if (buf.startsWith("$-1")) return finish(null);
      const m = /^\$(\d+)\r\n/.exec(buf);
      if (m && buf.length >= m[0].length + Number(m[1]) + 2) return finish(buf.slice(m[0].length, m[0].length + Number(m[1])));
      if (/^[+:]/.test(buf) && buf.includes("\r\n")) return finish(buf.slice(1, buf.indexOf("\r\n")));
      if (buf.startsWith("-")) return fail(new Error(buf.trim()));
    });
    sock.on("error", reject);
    const finish = (v) => { sock.end(); resolve(v); };
    const fail = (e) => { sock.destroy(); reject(e); };
  });
}

/** Koneksi persisten untuk PUBLISH berfrekuensi tinggi (balasan diabaikan). */
class Publisher {
  constructor() { this.connect(); }
  connect() {
    this.sock = net.createConnection(REDIS_PORT, REDIS_HOST);
    this.sock.on("data", () => {});
    this.sock.on("error", (e) => log("Redis error:", e.message));
    this.sock.on("close", () => setTimeout(() => this.connect(), 1000));
  }
  send(args) {
    if (this.sock.writable) this.sock.write(encode(args));
  }
}

// ---------- Streaming ----------

async function wantedSymbols() {
  for (;;) {
    try {
      const raw = await redisOnce(["GET", "stream:wanted"]);
      const list = raw ? JSON.parse(raw) : [];
      if (list.length) return list;
    } catch (e) {
      log("Belum bisa membaca daftar simbol dari Redis:", e.message);
    }
    await sleep(5000);
  }
}

function session(symbols, publisher) {
  return new Promise((resolve) => {
    const ws = new WebSocket(URL + API_KEY);
    let streamed = 0;
    let heartbeat;
    ws.onopen = () => {
      log("Tersambung ke Twelve Data, subscribe:", symbols.join(","));
      ws.send(JSON.stringify({ action: "subscribe", params: { symbols: symbols.join(",") } }));
      heartbeat = setInterval(() => ws.send(JSON.stringify({ action: "heartbeat" })), HEARTBEAT_MS);
    };
    ws.onmessage = (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch { return; }
      if (msg.event === "price" && msg.price != null) {
        publisher.send(["PUBLISH", "ticks:raw", JSON.stringify({ symbol: msg.symbol, price: Number(msg.price) })]);
      } else if (msg.event === "subscribe-status") {
        const success = (msg.success ?? []).map((s) => s.symbol);
        const fails = (msg.fails ?? []).map((s) => s.symbol);
        streamed = success.length;
        publisher.send(["SET", "stream:status", JSON.stringify({ success, fails })]);
        log("Streaming:", success.join(",") || "-", "| ditolak paket:", fails.join(",") || "-");
        if (!success.length) ws.close();
      }
    };
    ws.onerror = () => log("WebSocket error");
    ws.onclose = (e) => {
      clearInterval(heartbeat);
      publisher.send(["DEL", "stream:status"]);
      log("Koneksi tertutup", e.code);
      resolve(streamed);
    };
  });
}

async function main() {
  if (!API_KEY) {
    log("TWELVEDATA_API_KEY kosong — streamer tidak berjalan.");
    for (;;) await sleep(3_600_000);
  }
  const publisher = new Publisher();
  let backoff = 1000;
  for (;;) {
    const symbols = await wantedSymbols();
    const streamed = await session(symbols, publisher);
    backoff = streamed ? 1000 : Math.min(backoff * 2, MAX_BACKOFF_MS);
    log(`Menyambung ulang dalam ${backoff / 1000} dtk`);
    await sleep(backoff);
  }
}

main();
