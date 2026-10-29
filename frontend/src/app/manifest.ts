import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "SignalFlow — Sinyal Trading M15",
    short_name: "SignalFlow",
    description: "Sinyal BUY/SELL/CLOSE/WAIT M15 untuk dieksekusi manual di aplikasi broker",
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#0b0e11",
    theme_color: "#0b0e11",
    lang: "id",
    icons: [
      { src: "/icons/192", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/512", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/512", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
