import { ImageResponse } from "next/og";

const BG = "#0b0e11";
const UP = "#16c784";
const DOWN = "#ea3943";

// [warna, posisi atas sumbu (%), tinggi badan (%), tinggi sumbu (%)]
const CANDLES: [string, number, number, number][] = [
  [UP, 40, 28, 44],
  [DOWN, 28, 30, 46],
  [UP, 14, 42, 60],
];

/** Ikon aplikasi: tiga candle di latar gelap (aman untuk ikon 'maskable'). */
export function appIcon(size: number): ImageResponse {
  const bodyWidth = size * 0.13;
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          background: BG,
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "center",
          gap: size * 0.07,
          paddingTop: size * 0.16,
        }}
      >
        {CANDLES.map(([color, top, body, wick], i) => (
          <div
            key={i}
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              marginTop: (size * top) / 100 - size * 0.1,
              height: (size * wick) / 100,
              position: "relative",
            }}
          >
            <div style={{ width: size * 0.025, height: "100%", background: color, borderRadius: size }} />
            <div
              style={{
                position: "absolute",
                top: (size * (wick - body)) / 200,
                width: bodyWidth,
                height: (size * body) / 100,
                background: color,
                borderRadius: size * 0.02,
              }}
            />
          </div>
        ))}
      </div>
    ),
    { width: size, height: size },
  );
}
