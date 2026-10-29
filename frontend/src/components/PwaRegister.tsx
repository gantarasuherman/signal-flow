"use client";

import { useEffect } from "react";

/** Daftarkan service worker agar dashboard bisa dipasang sebagai aplikasi (PWA). */
export function PwaRegister() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    // Browser hanya mengizinkan service worker di HTTPS atau localhost
    navigator.serviceWorker.register("/sw.js").catch(() => undefined);
  }, []);
  return null;
}
