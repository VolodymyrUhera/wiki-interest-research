"""Rendering: chart PNG, one-page PDF and the Markdown summary printed to the agent."""
import statistics
import textwrap
from datetime import date, datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from analysis import _pct  # noqa: E402

METHOD = (
    "Method: daily Wikimedia pageviews (agent=user, all platforms) for each article plus its redirects. "
    "Typical-day change = median daily views in the last window vs the first window (robust to spikes); "
    "total change = sum of views; 'vs wiki' divides by the change in total traffic of that language edition. "
    "Trend p = Mann-Kendall test on monthly totals (p<0.10 = consistent trend). "
    "Limitations: pageviews measure attention, not willingness to pay; one article is a proxy for a topic; "
    "automated traffic is only partly filtered; views depend on wiki size, search engines and AI answers; "
    "news events create spikes; languages are not countries."
)


def _dates(months):
    return [datetime.strptime(m, "%Y-%m") for m in months]


def _index(values, base_n=3):
    base = [v for v in values[:base_n] if v]
    b = sum(base) / len(base) if base else None
    return [v / b * 100 if v is not None and b else None for v in values]


def _draw(ax1, ax2, results):
    for r in results:
        m = r["metrics"]
        x = _dates(m["months"])
        ax1.plot(x, m["monthly_views"], lw=1.6, label=r["label"])
        ax2.plot(x, _index(m["monthly_share_ppm"]), lw=1.6, label=r["label"])
    vals = [v for r in results for v in r["metrics"]["monthly_views"] if v > 0]
    if vals and max(vals) / min(vals) > 30:
        ax1.set_yscale("log")
    ax1.set_title("Monthly views (incl. redirects)", fontsize=9)
    ax2.set_title("Relative to whole-wiki traffic (first 3 months = 100)", fontsize=9)
    ax2.axhline(100, color="grey", lw=0.8, ls=":")
    for ax in (ax1, ax2):
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
        ax.tick_params(labelsize=7)
        ax.grid(alpha=0.3)
    ax1.legend(fontsize=6 if len(results) > 5 else 7, frameon=False, ncol=2 if len(results) > 5 else 1)


def chart_png(results, path):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), constrained_layout=True)
    _draw(ax1, ax2, results)
    fig.savefig(path, dpi=130)
    plt.close(fig)


PROXY_SIZE = "n/a (proxy)"


def _size_cells(r):
    """Views/day and per-1M cells. A proxy article measures a different concept, so its size is not shown at all."""
    m = r["metrics"]
    if r.get("proxy"):
        return [PROXY_SIZE, PROXY_SIZE]
    ppm = m["share_ppm_last"]
    return [f"{m['avg_daily_last']:.0f}", "n/a" if ppm is None else f"{ppm:.1f}"]


def table_rows(results):
    rows = []
    for r in results:
        m = r["metrics"]
        rows.append([r["label"], r["article"][:28], *_size_cells(r),
                     f"{_pct(m['growth_robust'])} ({m['direction']})",
                     _pct(m["growth_total"]), f"{_pct(m['growth_normalized'])} ({m['direction_vs_wiki']})",
                     f"{m['mann_kendall_p']:.2f}", m["confidence"]])
    return rows


HEADER = ["Series", "Article", "Views/day", "Per 1M views", "Typical-day Δ", "Total Δ", "vs wiki Δ", "Trend p",
          "Confidence"]


def pdf(study, path):
    """One A4 page: title, findings, metrics table, two charts, caveats, method."""
    results = study["results"]
    fig = plt.figure(figsize=(8.27, 11.69))
    y = 0.965

    def text(s, size=8.5, width=None, gap=1.45, **kw):
        nonlocal y
        # ~0.58 em per character across the 0.88-wide text column (Cyrillic glyphs are wider than Latin)
        width = width or int(0.88 * 8.27 * 72 / (size * 0.58))
        for line in textwrap.wrap(s, width) or [""]:
            fig.text(0.06, y, line, fontsize=size, va="top", **kw)
            y -= size * gap / 72 / 11.69

    text(study["title"], size=15, width=55, weight="bold")
    text(f"Wikipedia pageviews · {study['start']} to {study['end']} · {study['window']} · generated {date.today()}",
         size=8, color="dimgrey")
    if study.get("question"):
        text(textwrap.shorten(f"Question: {study['question']}", 240, placeholder="…"), size=8.5, style="italic")
    y -= 0.008
    text("Key findings", size=10.5, weight="bold")
    findings = study.get("notes") or [r["summary"] for r in results]
    # Findings are capped (7 × ~2 lines) so the table and charts always keep their space on the page.
    for f in findings[:7]:
        text("• " + textwrap.shorten(f, 250, placeholder="…"))
    y -= 0.008

    shown = results[:10]
    h = 0.0175 * (len(shown) + 1)
    ax = fig.add_axes([0.06, y - h, 0.88, h])
    ax.axis("off")
    tbl = ax.table(cellText=table_rows(shown), colLabels=HEADER, loc="upper center", cellLoc="left",
                   colWidths=[0.16, 0.14, 0.08, 0.09, 0.14, 0.07, 0.13, 0.06, 0.09])
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(7)
    for (row, _), cell in tbl.get_celld().items():
        cell.set_linewidth(0.3)
        if row == 0:
            cell.set_facecolor("#eeeeee")
    y -= h + 0.015
    if len(results) > len(shown):
        text(f"{len(results) - len(shown)} more series in results.json", size=7, color="dimgrey")

    # Charts take whatever height is left above caveats + method (~0.2 of the page), capped.
    ch = max(0.15, min(0.34, y - 0.24))
    ax1 = fig.add_axes([0.08, y - ch, 0.4, ch - 0.02])
    ax2 = fig.add_axes([0.56, y - ch, 0.4, ch - 0.02])
    _draw(ax1, ax2, results)
    y -= ch + 0.035

    text("Caveats", size=10.5, weight="bold")
    caveats = [f"{r['label']}: " + "; ".join(r["metrics"]["flags"]) for r in results if r["metrics"]["flags"]]
    caveats += [f"{s['label']}: no article in this language (not included)" for s in study.get("missing", [])]
    caveats += [f"{r['label']}: proxy article '{r['article']}', compare trend only, not size"
                for r in results if r.get("proxy")]
    caveats += [f"{r['label']}: likely stub ({_size_cells(r)[1]} per 1M vs {med:.1f} median elsewhere), "
                "excluded from rankings" for r, med in stubs(results)]
    caveats = caveats or ["No data-quality flags raised."]
    caveats.insert(0, wiki_traffic_line(results))
    for i, c in enumerate(caveats):
        if y < 0.1:  # keep ~0.07 of the page for the method paragraph
            text(f"• {len(caveats) - i} more in results.json", size=7.5, color="dimgrey")
            break
        text("• " + textwrap.shorten(c, 180, placeholder="…"), size=7.5)
    text(METHOD, size=6.5, color="dimgrey")
    fig.savefig(path)
    plt.close(fig)


ANSWER_HEADER = ["Series (article)", "Views/day", "Per 1M views", "Typical-day Δ", "vs wiki Δ", "Confidence"]


def answer_rows(results, controls=()):
    """The table the agent pastes into its reply: same columns as SKILL.md's template, verdict words included.

    Control-topic rows go last and are marked, so the yardstick is not read as a candidate.
    """
    results = sorted(results, key=lambda r: r.get("topic") in controls)
    return [[f"{r['label']}{' (control)' * (r.get('topic') in controls)} ({r['article']})", *_size_cells(r), f"{_pct(r['metrics']['growth_robust'])} "
             f"({r['metrics']['direction']})", f"{_pct(r['metrics']['growth_normalized'])} "
             f"({r['metrics']['direction_vs_wiki']})", r["metrics"]["confidence"]] for r in results]


def _md_table(header, rows):
    return ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)] + ["| " + " | ".join(r) + " |" for r in rows]


def markdown(study):
    lines = [f"# {study['title']}", f"Period {study['start']}..{study['end']} ({study['window']})", "",
             "ANSWER TABLE (paste into your reply unchanged; translate only the header):"]
    lines += _md_table(ANSWER_HEADER, answer_rows(study["results"], study.get("controls", [])))
    lines += ["", "Details:"] + _md_table(HEADER, table_rows(study["results"]))
    lines += rankings(study["results"], study.get("rank_by", "relative"), study.get("controls", []))
    lines += control_checks(study["results"], study.get("controls", []))
    lines += ["", wiki_traffic_line(study["results"]) + " (quote this instead of general claims about Wikipedia; "
              "compare topics via vs wiki Δ, not against this)"]
    lines.append("")
    for r in study["results"]:
        m = r["metrics"]
        extra = [f"redirects {r['redirect_share']:.0%} of views"] if r["redirect_share"] >= 0.05 else []
        if m["spike_days"]:
            extra.append("spikes " + ", ".join(f"{s['date']} ({s['views']})" for s in m["spike_days"]))
        lines.append(f"- {r['summary']}" + (f" [{'; '.join(extra)}]" if extra else ""))
        lines += [f"  - flag: {f}" for f in m["flags"]]
    proxies = [r["label"] for r in study["results"] if r.get("proxy")]
    if proxies:
        lines.append(f"- PROXY {', '.join(proxies)}: manually chosen article, maybe broader/narrower than the topic. "
                     "Compare its trend only; its size (views, per 1M) is NOT comparable with other languages")
    for r, others in stubs(study["results"]):
        lines.append(f"- STUB? {r['label']} ({r['article']}): {_size_cells(r)[1]} per 1M vs {others:.1f} median in other "
                     f"languages; linked article may be a stub or a side page. Run `search` in {r['lang']} and, if a "
                     f"better article exists, pass --article \"{r['topic']}={r['lang']}:<Title>\"")
    for s in study.get("missing", []):
        lines.append(f"- MISSING {s['label']}: no article found; run `search` and pass --article \"{s['topic']}={s['lang']}:<Title>\"")
    return "\n".join(lines)


STUB_RATIO = 0.1  # ponytail: fixed cutoff vs other languages' median; tune if real articles get flagged


def stubs(results):
    """Auto-linked articles with far less relative interest than the same topic elsewhere: likely a stub, not a niche."""
    out = []
    for r in results:
        ppm = r["metrics"]["share_ppm_last"]
        if r.get("proxy") or ppm is None:
            continue
        others = [o["metrics"]["share_ppm_last"] for o in results if o is not r and o["topic"] == r["topic"]
                  and not o.get("proxy") and o["metrics"]["share_ppm_last"] is not None]
        if others and ppm < STUB_RATIO * statistics.median(others):
            out.append((r, statistics.median(others)))
    return out


def wiki_traffic_line(results):
    """Each wiki's own change in total views over the same windows; 'n/a' where a whole-wiki month is missing."""
    # All series of one language share dates and whole-wiki data, so any of them gives the same value.
    wiki = {r["lang"]: r["metrics"].get("growth_project") for r in results}
    cells = ", ".join(f"{lang} {'n/a' if g is None else _pct(g)}" for lang, g in sorted(wiki.items()))
    return f"WHOLE-WIKI TRAFFIC Δ, total views: {cells or 'n/a'}"


def control_checks(results, controls):
    """Topic vs its control, per language, on vs wiki Δ: spelled out so the agent does not eyeball the gap."""
    lines = []
    for c in (r for r in results if r["topic"] in controls and r["metrics"]["growth_normalized"] is not None):
        for r in results:
            g = r["metrics"]["growth_normalized"]
            if r["topic"] in controls or r["lang"] != c["lang"] or g is None or r.get("proxy"):
                continue
            gap = g - c["metrics"]["growth_normalized"]
            verdict = ("moves with its field (gap within 10 points)" if abs(gap) <= 0.10 else
                       f"{'better' if gap > 0 else 'worse'} than its field by {abs(gap) * 100:.0f} points "
                       "(topic-specific)")
            lines.append(f"- CONTROL CHECK {r['lang']}: {r.get('name', r['topic'])} {_pct(g)} vs wiki, "
                         f"{c.get('name', c['topic'])} (control) {_pct(c['metrics']['growth_normalized'])}: {verdict}")
    return ([""] + lines) if lines else []


def _chain(items, tie):
    """items: [(name, value)] sorted desc. Joins with ≈ when tie(prev, next) else >."""
    out = f"{items[0][0]} {items[0][2]}"
    for (_, prev, _), (name, val, shown) in zip(items, items[1:], strict=False):
        out += (" ≈ " if tie(prev, val) else " > ") + f"{name} {shown}"
    return out + ("  → no clear leader" if tie(items[0][1], items[1][1]) else "")


def tiers(rs, rank_by, name):
    """Decision rule from SKILL.md, computed here so the agent copies it instead of re-judging.

    Size measure = per 1M views (relative) or views/day (audience); "top half" = at least half of the largest.
    explore now = top half and not declining vs wiki (audience: top half regardless of momentum, since the user
    ranked size above pace); skip = low confidence, or bottom half and declining; watch = everything else.
    `name(r)` is how a series is called in this group (its language, or its topic).
    """
    def size(m):
        return m["share_ppm_last"] if rank_by == "relative" else m["avg_daily_last"]

    ok = sorted((r for r in rs if not r.get("proxy") and size(r["metrics"]) is not None),
                key=lambda r: -size(r["metrics"]))
    if len(ok) < 2 or not size(ok[0]["metrics"]):
        return []
    top = size(ok[0]["metrics"])
    out = {"explore now": [], "watch": [], "skip": []}
    for r in ok:
        m = r["metrics"]
        big = size(m) >= 0.5 * top
        mom = m["direction_vs_wiki"]
        if m["confidence"] == "low":
            tier = "skip"
        elif big and (rank_by == "audience" or mom in ("growing", "flat")):
            tier = "explore now"
        elif not big and mom == "declining":
            tier = "skip"
        else:
            tier = "watch"
        shown = f"{size(m):.1f} per 1M" if rank_by == "relative" else f"{size(m):.0f} views/day"
        out[tier].append(f"{name(r)} ({shown}, {'top' if big else 'bottom'} half; "
                         f"{mom} vs wiki {_pct(m['growth_normalized'])}; confidence {m['confidence']})")
    rule = ("relative interest (per 1M views), then momentum vs wiki" if rank_by == "relative" else
            "audience size (views/day); top half = explore now whatever the momentum")
    return [f"- SUGGESTED TIERS (rule: {rule}; low confidence = skip; copy these, do not re-rank):"] + [
        f"  - {tier}: " + ("; ".join(items) if items else "none") for tier, items in out.items()]


def _group_ranking(rs, title, name, rank_by, control=False):
    """Chains (ties explicit, not left to the reader's judgment) and tiers for one comparable group."""
    size = sorted(((name(r), r["metrics"]["share_ppm_last"]) for r in rs
                   if r["metrics"]["share_ppm_last"] is not None and not r.get("proxy")), key=lambda x: -x[1])
    mom = sorted(((name(r), r["metrics"]["growth_normalized"]) for r in rs
                  if r["metrics"]["growth_normalized"] is not None), key=lambda x: -x[1])
    if len(size) < 2 and len(mom) < 2:
        return []
    return ["", f"Ranking {title} (≈ = tie: within 10%):",
            "- relative interest, per 1M views (proxies and STUB? excluded): "
            + (_chain([(n, v, f"{v:.1f}") for n, v in size], lambda a, b: b >= 0.9 * a)
               if len(size) > 1 else "not comparable"),
            "- momentum, vs wiki Δ: "
            + (_chain([(n, v, _pct(v)) for n, v in mom], lambda a, b: round(a - b, 2) <= 0.10)
               if len(mom) > 1 else "not comparable")] + (
        ["- (control topic: a yardstick for the topics above, not a candidate; no tiers)"] if control
        else tiers(rs, rank_by, name))


def rankings(results, rank_by="relative", controls=()):
    """One group per topic (compare languages) and, with 2+ topics, one per language (compare topics).

    STUB? series are left out (their size is an artifact, not interest); control topics are left out of the
    topic groups, since they are a yardstick, not a candidate.
    """
    stub_ids = {id(r) for r, _ in stubs(results)}
    results = [r for r in results if id(r) not in stub_ids]
    lines = []
    for topic in dict.fromkeys(r["topic"] for r in results):
        rs = [r for r in results if r["topic"] == topic]
        lines += _group_ranking(rs, f"of languages for {rs[0].get('name', topic)}", lambda r: r["lang"], rank_by,
                                control=topic in controls)
    candidates = [r for r in results if r["topic"] not in controls]
    if len({r["topic"] for r in candidates}) > 1:
        for lang in dict.fromkeys(r["lang"] for r in candidates):
            rs = [r for r in candidates if r["lang"] == lang]
            lines += _group_ranking(rs, f"of topics in {lang}", lambda r: r.get("name", r["topic"]), rank_by)
    return lines
