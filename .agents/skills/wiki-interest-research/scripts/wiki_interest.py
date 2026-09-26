# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.8,<4"]
# ///
"""Wikipedia interest research CLI. Run `uv run scripts/wiki_interest.py -h`."""
import argparse
import csv
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import analysis
import wikiapi


def last_complete_month_end(today=None):
    # Data for a day loads after it ends (UTC), so on the 1st the previous month may still be incomplete.
    today = today or datetime.now(timezone.utc).date() - timedelta(days=1)
    return today.replace(day=1) - timedelta(days=1)


def month_arg(text):
    """argparse type for YYYY-MM -> (year, month)."""
    try:
        y, m = map(int, text.split("-"))
        date(y, m, 1)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' is not a month like 2025-01") from None
    return y, m


def positive_int(text):
    if not text.isdigit() or int(text) < 1:
        raise argparse.ArgumentTypeError(f"'{text}' must be a positive whole number")
    return int(text)


def parse_period(args):
    end = last_complete_month_end()
    if args.end:
        y, m = args.end
        end = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
    if args.start:
        y, m = args.start
        start = date(y, m, 1)
    else:
        y, m = end.year, end.month - args.months + 1
        while m < 1:
            y, m = y - 1, m + 12
        start = date(y, m, 1)
    if start < date(2015, 7, 1):
        sys.exit("error: pageview data starts 2015-07")
    if start > end:
        sys.exit("error: start is after end")
    if (end.year - start.year) * 12 + end.month - start.month + 1 < 2:
        sys.exit("error: the period must cover at least 2 months (24 or more recommended)")
    if end > last_complete_month_end():
        sys.exit(f"error: --end must be a complete month (latest: {last_complete_month_end():%Y-%m})")
    return start, end


def split_langs(values):
    """Accept both `--langs pl,cs` and `--langs pl cs`."""
    return list(dict.fromkeys(code.strip().lower() for v in values for code in v.split(",") if code.strip()))


def check_langs(langs):
    """Fail fast on codes that are not Wikipedia editions (e.g. country codes), instead of reporting them MISSING."""
    sites = wikiapi.wikipedia_sites()
    unknown = [lang for lang in langs if lang not in sites]
    if unknown:
        sys.exit(f"error: unknown Wikipedia language code(s): {', '.join(unknown)} (use wiki codes like uk, cs, pl)")


def cmd_resolve(args):
    langs = split_langs(args.langs)
    check_langs(langs)
    print(json.dumps(wikiapi.resolve(args.topic, args.source_lang, langs), ensure_ascii=False, indent=1))


def cmd_search(args):
    if not args.query.strip():
        sys.exit("error: empty search query")
    check_langs([args.lang])
    for r in wikiapi.search(args.query, args.lang, args.limit):
        print(f"{r['title']}\t({r['words']} words)")


def label(lang, topic):
    t = topic.replace("_", " ")
    return f"{lang}:{t if len(t) <= 26 else t[:25] + '…'}"


def parse_article(spec, topics):
    """'lang:Title' or 'Topic=lang:Title' -> (topic, lang, title). Titles may contain '=' and ':'."""
    topic, sep, rest = spec.partition("=")
    if not sep or topic not in topics:
        topic, rest = topics[0], spec
    lang, _, title = rest.partition(":")
    if not re.fullmatch(r"[a-z][a-z0-9-]*", lang) or not title.strip():
        raise ValueError(f"--article '{spec}' must look like 'pl:Title' or 'Topic=pl:Title'")
    return topic, lang, title.strip()


def build_series(args):
    """Returns (series, missing): series = [{label, topic, lang, article}] to fetch."""
    langs = split_langs(args.langs)
    check_langs(langs)
    series, missing, qids, names = [], [], {}, {}
    for topic in args.topic:
        res = wikiapi.resolve(topic, args.source_lang, langs)
        qids[topic] = res.get("qid")
        # A QID topic is shown by its Wikidata label ("physics"), not "Q413".
        names[topic] = res.get("label", topic) if wikiapi.is_qid(topic) else topic
        if "error" in res:
            sys.exit(f"error: {res['error']}")
        for lang, title in res["titles"].items():
            entry = {"label": label(lang, names[topic]), "topic": topic, "name": names[topic], "lang": lang,
                     "article": title}
            (series if title else missing).append(entry)
    for spec in args.article or []:
        try:
            topic, lang, title = parse_article(spec, args.topic)
        except ValueError as e:
            sys.exit(f"error: {e}")
        check_langs([lang])
        canon, qid = wikiapi.canonical(lang, title)
        if canon is None:
            sys.exit(f"error: no article '{title}' on {lang}.wikipedia (use the search command)")
        series = [s for s in series if not (s["topic"] == topic and s["lang"] == lang)]
        missing = [s for s in missing if not (s["topic"] == topic and s["lang"] == lang)]
        # '*' marks a proxy: an article about a different Wikidata item than the topic in other languages.
        proxy = qid is None or qid != qids.get(topic)
        series.append({"label": label(lang, names[topic]) + "*" * proxy, "topic": topic, "name": names[topic],
                       "lang": lang, "article": canon, "proxy": proxy})
    return series, missing, names


def fetch(series, start, end, with_redirects, max_redirects):
    # Sequential on purpose: the Analytics API access policy asks clients to wait for each request to finish.
    # ponytail: slow on a cold cache with many redirects; repeat runs hit the cache.
    redirect_lists = [wikiapi.redirects(s["lang"], s["article"])[:max_redirects] if with_redirects else []
                      for s in series]
    pages = sorted({(s["lang"], t) for s, rl in zip(series, redirect_lists, strict=True) for t in [s["article"], *rl]})
    daily = {p: wikiapi.article_daily(p[0], p[1], start, end) for p in pages}
    project = {lang: wikiapi.project_monthly(lang, start, end) for lang in sorted({s["lang"] for s in series})}
    out = []
    for s, rl in zip(series, redirect_lists, strict=True):
        combined = dict(daily[(s["lang"], s["article"])])
        for t in rl:
            for d, v in daily[(s["lang"], t)].items():
                combined[d] = combined.get(d, 0) + v
        main_total = sum(daily[(s["lang"], s["article"])].values())
        total = sum(combined.values())
        out.append((s, combined, project[s["lang"]], len(rl), (total - main_total) / total if total else 0.0))
    return out


def cmd_study(args):
    start, end = parse_period(args)
    args.topic = list(dict.fromkeys(args.topic + args.control))
    series, missing, names = build_series(args)
    if not series:
        sys.exit("error: no articles found for any language; use the search command and pass --article lang:Title")
    results = []
    for s, daily, project, n_redirects, redirect_share in fetch(series, start, end, not args.no_redirects,
                                                              args.max_redirects):
        m = analysis.analyze(daily, project, start, end)
        results.append({**s, "redirects": n_redirects, "redirect_share": redirect_share, "metrics": m,
                        "summary": analysis.one_line(s["label"], m, s.get("proxy", False))})
    results.sort(key=lambda r: (r["metrics"]["growth_robust"] is None, -(r["metrics"]["growth_robust"] or 0)))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    study = {"title": args.title or " vs ".join(names.values()) + " — Wikipedia interest",
             "question": args.question, "notes": args.note or [], "start": start.isoformat(),
             "end": end.isoformat(), "window": results[0]["metrics"]["window"], "topics": args.topic,
             "results": results, "missing": missing, "rank_by": args.rank_by, "controls": args.control}
    write_outputs(study, out)
    print(render(study, out))


def write_outputs(study, out):
    import report  # matplotlib import is slow; only load when rendering

    (out / "results.json").write_text(json.dumps(study, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(out / "series.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["label", "lang", "article", "month", "views", "share_per_million_wiki_views"])
        for r in study["results"]:
            m = r["metrics"]
            for month, v, s in zip(m["months"], m["monthly_views"], m["monthly_share_ppm"], strict=True):
                w.writerow([r["label"], r["lang"], r["article"], month, v, "" if s is None else round(s, 3)])
    report.chart_png(study["results"], out / "chart.png")
    report.pdf(study, out / "report.pdf")


def render(study, out):
    import report

    files = ", ".join(str(out / f) for f in ("report.pdf", "chart.png", "results.json", "series.csv"))
    return report.markdown(study) + f"\n\nFiles: {files}"


def cmd_report(args):
    out = Path(args.dir)
    if not (out / "results.json").exists():
        sys.exit(f"error: {out} has no results.json; run `study --out {out}` first")
    try:
        study = json.loads((out / "results.json").read_text(encoding="utf-8"))
        study["results"][0]["metrics"]
    except (ValueError, KeyError, TypeError, IndexError):
        sys.exit(f"error: {out}/results.json is damaged or has no results; rerun `study --out {out}`")
    if args.title:
        study["title"] = args.title
    if args.question:
        study["question"] = args.question
    if args.note:
        study["notes"] = args.note
    write_outputs(study, out)
    print(f"Updated {out / 'report.pdf'} ({len(study['notes'])} findings)")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("resolve", help="find the article for a topic in each language (via Wikidata)")
    r.add_argument("topic", help="article title in --source-lang, or Wikidata QID")
    r.add_argument("--langs", required=True, nargs="+", action="extend", help="wiki codes, e.g. pl,cs,uk")
    r.add_argument("--source-lang", default="en")
    r.set_defaults(func=cmd_resolve)

    s = sub.add_parser("search", help="search article titles in one language edition")
    s.add_argument("query")
    s.add_argument("--lang", required=True)
    s.add_argument("--limit", type=positive_int, default=5)
    s.set_defaults(func=cmd_search)

    st = sub.add_parser("study", help="fetch, analyze, chart and write a one-page PDF")
    st.add_argument("--topic", action="append", required=True,
                    help="article title in --source-lang or QID; repeat to compare topics")
    st.add_argument("--control", action="append", default=[],
                    help="control topic (same field): analyzed like --topic but never a candidate in topic tiers")
    st.add_argument("--langs", required=True, nargs="+", action="extend", help="wiki codes, e.g. pl,cs (not country codes)")
    st.add_argument("--source-lang", default="en", help="language of the --topic titles (default en)")
    st.add_argument("--article", action="append",
                    help="override/add an article: 'lang:Title' or 'Topic=lang:Title'; repeatable")
    st.add_argument("--months", type=positive_int, default=24,
                    help="number of complete months ending last month (default 24)")
    st.add_argument("--start", type=month_arg, help="YYYY-MM (overrides --months)")
    st.add_argument("--end", type=month_arg, help="YYYY-MM (default: last complete month)")
    st.add_argument("--no-redirects", action="store_true", help="count only the main article title")
    st.add_argument("--max-redirects", type=positive_int, default=50)
    st.add_argument("--rank-by", choices=["relative", "audience"], default="relative",
                    help="tier rule: relative interest (per 1M views, default) or audience size (views/day)")
    st.add_argument("--title", help="report title")
    st.add_argument("--question", help="the user's question, printed on the report")
    st.add_argument("--note", action="append", help="a key finding for the PDF (repeatable); default = auto")
    st.add_argument("--out", required=True, help="output directory")
    st.set_defaults(func=cmd_study)

    rp = sub.add_parser("report", help="re-render the PDF of an existing study with new title/notes (no refetch)")
    rp.add_argument("dir")
    rp.add_argument("--title")
    rp.add_argument("--question")
    rp.add_argument("--note", action="append", help="key finding (repeatable); replaces previous notes")
    rp.set_defaults(func=cmd_report)

    sys.stdout.reconfigure(encoding="utf-8")  # the summary has Δ ≈ → and non-Latin titles, even on Windows
    args = p.parse_args(argv)
    try:
        args.func(args)
    except (OSError, RuntimeError) as e:  # URLError/HTTPError are OSErrors; the agent needs one line, not a traceback
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
