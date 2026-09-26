"""Pure metrics for one pageview series. No I/O, so it is unit-testable offline.

See references/methodology.md for the meaning of every field and the confidence rules.
"""
import math
from datetime import timedelta
from statistics import fmean, linear_regression, median

GROWTH_FLAT = 0.10      # |robust growth| below this is called "flat"
LOW_VOLUME = 20         # avg views/day below this makes percentages noisy
VERY_LOW_VOLUME = 5
SPIKE_SHARE = 0.20      # top-7-days share of views above this = spike-driven
MK_ALPHA = 0.10


def days_between(start, end):
    return [(start + timedelta(d)).isoformat() for d in range((end - start).days + 1)]


def month_list(start, end):
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def mann_kendall(xs):
    """Mann-Kendall monotonic trend test (normal approximation, no tie correction). Returns (S, two-sided p)."""
    n = len(xs)
    s = sum((xs[j] > xs[i]) - (xs[j] < xs[i]) for i in range(n) for j in range(i + 1, n))
    var = n * (n - 1) * (2 * n + 5) / 18
    if var == 0:
        return 0, 1.0
    z = (s - (s > 0) + (s < 0)) / math.sqrt(var)
    return s, math.erfc(abs(z) / math.sqrt(2))


def _ratio(a, b):
    return a / b - 1 if b else None


def analyze(daily, project_monthly, start, end):
    """daily: {'YYYY-MM-DD': views} (missing days = 0); project_monthly: {'YYYY-MM': views} of the whole wiki."""
    days = days_between(start, end)
    views = [daily.get(d, 0) for d in days]
    months = month_list(start, end)
    monthly = {m: 0 for m in months}
    for d, v in zip(days, views, strict=True):
        monthly[d[:7]] += v
    mvals = [monthly[m] for m in months]
    total = sum(views)

    k = min(12, len(months) // 2)
    first, last = months[:k], months[-k:]
    first_days = [v for d, v in zip(days, views, strict=True) if d[:7] in first]
    last_days = [v for d, v in zip(days, views, strict=True) if d[:7] in last]
    g_total = _ratio(sum(monthly[m] for m in last), sum(monthly[m] for m in first))
    g_robust = _ratio(median(last_days), median(first_days)) if k else None
    # A month missing from the whole-wiki totals (not yet published) would bias normalization; don't guess.
    proj_missing = [m for m in first + last if not project_monthly.get(m)]
    proj_first = sum(project_monthly.get(m, 0) for m in first)
    proj_last = sum(project_monthly.get(m, 0) for m in last)
    g_project = None if proj_missing else _ratio(proj_last, proj_first)

    def normalized(g):
        return None if g is None or g_project is None else (1 + g) / (1 + g_project) - 1

    # Log-linear trend over monthly totals: annualized growth rate and fit quality.
    if len(mvals) >= 3 and len(set(mvals)) > 1:
        ys = [math.log(v + 1) for v in mvals]
        slope, intercept = linear_regression(range(len(ys)), ys)
        fitted = [intercept + slope * i for i in range(len(ys))]
        ss_tot = sum((y - fmean(ys)) ** 2 for y in ys)
        r2 = 1 - sum((y - f) ** 2 for y, f in zip(ys, fitted, strict=True)) / ss_tot if ss_tot else 0.0
        trend = {"annual_rate": math.exp(12 * slope) - 1, "r2": r2}
    else:
        trend = {"annual_rate": None, "r2": None}
    mk_s, mk_p = mann_kendall(mvals)

    top7 = sum(sorted(views, reverse=True)[:7]) / total if total else 0.0
    med = median(views)
    spikes = sorted(((v, d) for d, v in zip(days, views, strict=True) if v > max(5 * med, 50)), reverse=True)[:3]

    avg_daily = total / len(days)
    avg_daily_last = sum(last_days) / len(last_days) if last_days else 0.0
    avg_daily_first = sum(first_days) / len(first_days) if first_days else 0.0
    share_ppm = [monthly[m] / project_monthly[m] * 1e6 if project_monthly.get(m) else None for m in months]

    # Confidence: count independent reasons to doubt the growth number.
    flags, penalty = [], 0
    if avg_daily_last < VERY_LOW_VOLUME:
        flags.append(f"very low volume ({avg_daily_last:.1f} views/day): percentages are mostly noise")
        penalty += 2
    elif avg_daily_last < LOW_VOLUME:
        flags.append(f"low volume ({avg_daily_last:.0f} views/day): percentages are noisy")
        penalty += 1
    if avg_daily_last >= LOW_VOLUME and avg_daily_first < LOW_VOLUME:
        flags.append(f"small starting base ({avg_daily_first:.1f} views/day in the first window): growth % is inflated")
        penalty += 1
    if g_robust is None and total:
        flags.append("typical day was 0 views in the first window (new or very sparse article): no growth number")
        penalty += 2
    first_seen = next((d for d, v in zip(days, views, strict=True) if v), None)
    if first_seen and first_seen > days[min(30, len(days) - 1)]:
        flags.append(f"no views before {first_seen} (article created or renamed mid-period): growth is inflated")
        penalty += 1
    if k < 12:
        flags.append(f"compares {k}-month windows, so seasonality is not controlled; use >=24 months")
        penalty += 1
    # Total growth far from typical-day growth means a few days (news, viral links, bots) drive the number.
    # Different verdict words count only with a real gap: +9% vs +11% straddles the cutoff but agrees.
    spike_driven = top7 > SPIKE_SHARE or (
        g_total is not None and g_robust is not None and g_robust > -1
        and ((_direction(g_total) != _direction(g_robust) and abs(g_total - g_robust) > 0.05)
             or not 0.8 <= (1 + g_total) / (1 + g_robust) <= 1.25))
    if spike_driven:
        flags.append(f"spike-driven: top 7 days = {top7:.0%} of views; total vs typical-day growth "
                     f"{_pct(g_total)} vs {_pct(g_robust)}")
        penalty += 1
    if g_robust == -1 and g_total is not None and g_total > -0.5:
        flags.append(f"typical day fell to 0 but total views changed only {_pct(g_total)}: bursty traffic, "
                     "median unreliable")
        penalty += 1
    if mk_p > MK_ALPHA:
        flags.append(f"no consistent monthly trend (Mann-Kendall p={mk_p:.2f})")
        penalty += 1
    if proj_missing:
        flags.append(f"whole-wiki traffic missing for {', '.join(proj_missing)}: vs wiki Δ not computed")
        penalty += 1
    g_norm = normalized(g_robust)
    if g_robust is not None and g_norm is not None and abs(g_robust) > GROWTH_FLAT and (g_robust > 0) != (g_norm > 0):
        flags.append(f"direction reverses after adjusting for whole-wiki traffic (whole wiki {_pct(g_project)})")
        penalty += 1
    confidence = "high" if penalty == 0 else "medium" if penalty == 1 else "low"

    direction = _direction(g_robust)

    return {
        "window": f"last {k} vs first {k} months",
        "total_views": total,
        "avg_daily": round(avg_daily, 1),
        "avg_daily_last": round(avg_daily_last, 1),
        "growth_total": g_total,
        "growth_robust": g_robust,
        "growth_project": g_project,
        "growth_normalized": g_norm,
        "trend_annual_rate": trend["annual_rate"],
        "trend_r2": trend["r2"],
        "mann_kendall_s": mk_s,
        "mann_kendall_p": mk_p,
        "top7_share": top7,
        "spike_days": [{"date": d, "views": v} for v, d in spikes],
        "share_ppm_last": (sum(monthly[m] for m in last) / proj_last * 1e6)
        if proj_last and not proj_missing else None,
        "direction": direction,
        "direction_vs_wiki": _direction(g_norm),
        "confidence": confidence,
        "flags": flags,
        "months": months,
        "monthly_views": mvals,
        "monthly_share_ppm": share_ppm,
    }


def _direction(g):
    if g is None:
        return "insufficient data"
    return "growing" if g > GROWTH_FLAT else "declining" if g < -GROWTH_FLAT else "flat"


def _pct(x):
    return "n/a" if x is None else f"{x:+.0%}"


def one_line(label, m, proxy=False):
    """Short human-readable verdict for one series. A proxy's size is hidden: it measures a different concept."""
    size = "size n/a (proxy article)" if proxy else f"{m['avg_daily_last']:.0f} views/day"
    return (f"{label}: {m['direction']} {_pct(m['growth_robust'])} typical-day, "
            f"{m['direction_vs_wiki']} vs wiki traffic ({_pct(m['growth_normalized'])}; "
            f"total {_pct(m['growth_total'])}), "
            f"{size}, confidence {m['confidence']}")
