// Service worker SignalFlow: hanya agar aplikasi bisa dipasang sebagai PWA (Layar Utama).
// Data sinyal sengaja TIDAK di-cache agar yang tampil selalu sinyal terbaru.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
