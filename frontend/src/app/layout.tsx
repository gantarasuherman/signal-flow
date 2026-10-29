import type { Metadata, Viewport } from "next";
import { BottomNav } from "@/components/BottomNav";
import { PwaRegister } from "@/components/PwaRegister";
import { RealtimeProvider } from "@/lib/realtime";
import { THEME_INIT_SCRIPT, ThemeProvider } from "@/lib/theme";
import "./globals.css";

export const metadata: Metadata = {
  title: "SignalFlow",
  description: "Sinyal trading M15 untuk dieksekusi manual di aplikasi broker",
  applicationName: "SignalFlow",
  appleWebApp: { capable: true, title: "SignalFlow", statusBarStyle: "black-translucent" },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // Pinch dipakai untuk zoom grafik, bukan zoom halaman (seperti aplikasi broker)
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
  themeColor: "#0b0e11",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id" data-theme="dark" suppressHydrationWarning>
      <head>
        {/* Pasang tema sebelum halaman tampil agar tidak berkedip */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-screen pb-24">
        <ThemeProvider>
          <RealtimeProvider>
            {children}
            <BottomNav />
          </RealtimeProvider>
        </ThemeProvider>
        <PwaRegister />
      </body>
    </html>
  );
}
