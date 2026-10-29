"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

/** Alamat lama /instrument/XAUUSD → layar grafik utama /?s=XAUUSD */
export default function InstrumentRedirect() {
  const router = useRouter();
  const { symbol } = useParams<{ symbol: string }>();
  useEffect(() => router.replace(`/?s=${symbol.toUpperCase()}`), [router, symbol]);
  return null;
}
