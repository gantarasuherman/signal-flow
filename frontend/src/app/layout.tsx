import type { Metadata, Viewport } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import { BottomNav } from "@/components/BottomNav";
import { PwaRegister } from "@/components/PwaRegister";
import { RealtimeProvider } from "@/lib/realtime";
import { THEME_INIT_SCRIPT, ThemeProvider } from "@/lib/theme";
import "./globals.css";

const jakarta = Plus_Jakarta_Sans({ subsets: ["latin"], variable: "--font-jakarta", display: "swap" });

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
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f1f4f2" },
    { media: "(prefers-color-scheme: dark)", color: "#06120d" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id" data-theme="dark" className={jakarta.variable} suppressHydrationWarning>
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
