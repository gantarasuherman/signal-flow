"""Aturan validasi strategi.

Ditetapkan sebelum riset (agar tidak cherry-picking):
- Seleksi kandidat hanya memakai data in-sample: expectancy tertinggi dengan trade cukup.
- Lolos bila out-of-sample: profit factor >= MIN_OOS_PF, expectancy > 0, trade >= MIN_OOS_TRADES.

Diperketat setelah riset pertama (29 Okt 2026), hanya ke arah yang LEBIH ketat:
- In-sample juga harus tidak rugi (PF >= MIN_IS_PF). Strategi yang rugi di in-sample lalu
  sedikit untung di out-of-sample kemungkinan besar kebetulan.
"""

from typing import Any

MIN_IS_TRADES = 40
MIN_OOS_TRADES = 20
MIN_OOS_PF = 1.1
MIN_IS_PF = 1.0


def is_validated(out_of_sample: dict[str, Any], in_sample: dict[str, Any] | None = None) -> bool:
    oos_ok = (
        out_of_sample.get("trades", 0) >= MIN_OOS_TRADES
        and (out_of_sample.get("profit_factor") or 0) >= MIN_OOS_PF
        and (out_of_sample.get("expectancy_r") or 0) > 0
    )
    is_ok = in_sample is None or (in_sample.get("profit_factor") or 0) >= MIN_IS_PF
    return oos_ok and is_ok


def validation_reason(
    out_of_sample: dict[str, Any], in_sample: dict[str, Any] | None = None
) -> str:
    trades = out_of_sample.get("trades", 0)
    pf = out_of_sample.get("profit_factor")
    if trades < MIN_OOS_TRADES:
        return f"Trade out-of-sample terlalu sedikit ({trades} < {MIN_OOS_TRADES})."
    if in_sample is not None and (in_sample.get("profit_factor") or 0) < MIN_IS_PF:
        is_pf = in_sample.get("profit_factor")
        return f"Rugi di in-sample (PF {is_pf}), hasil out-of-sample tidak meyakinkan."
    if is_validated(out_of_sample, in_sample):
        return f"Lolos: out-of-sample PF {pf}, {trades} trade."
    return f"Belum lolos: out-of-sample PF {pf if pf is not None else '—'} ({trades} trade)."


def select_candidate(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pilih kandidat terbaik HANYA dari in-sample. `results`: [{name, in_sample, ...}]."""
    eligible = [r for r in results if r["in_sample"]["trades"] >= MIN_IS_TRADES]
    if not eligible:
        return None
    return max(eligible, key=lambda r: r["in_sample"]["expectancy_r"] or -99)
