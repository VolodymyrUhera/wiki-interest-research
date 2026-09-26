# wiki-interest-research: an Agent Skill

An [Agent Skill](https://agentskills.io/specification) that helps B2C founders decide which topics to build next
and which language audiences to launch in. It measures interest from Wikipedia pageviews and reports how much
each trend can be trusted.

```
wiki-interest-research/       ← the skill (self-contained; this README lives here too)
├── SKILL.md                  workflow, recipes, gotchas, answer template (~3k tokens)
├── scripts/
│   ├── wiki_interest.py      CLI: resolve | search | study | report   (PEP 723 deps → `uv run`)
│   ├── wiki_interest.py.lock exact dependency versions (uv script lock)
│   ├── wikiapi.py            MediaWiki / Wikidata / Pageviews clients + on-disk cache
│   ├── analysis.py           metrics, trust flags, confidence (pure, unit-tested)
│   └── report.py             chart PNG, one-page PDF, Markdown summary, rankings
├── references/methodology.md metric definitions and limitations (loaded on demand)
├── tests/                    unit tests: metrics (synthetic series), cache, CLI parsing, tier rule
├── evals/                    Haiku eval harness, prompts, grading checks + history, with/without and trigger sets
└── README.md                 this file: design, verification, roadmap
```

In this repository the skill is at `.agents/skills/wiki-interest-research/` (VS Code / Copilot default), and
`.claude/skills/wiki-interest-research` is a symlink to it so Claude Code finds the same skill. Commands below run
from the skill directory.

## Quick start

```bash
uv run scripts/wiki_interest.py study --topic "Astronomy" --control "Physics" --langs uk \
  --question "Is interest in astronomy growing?" --out /tmp/wiki-reports/astronomy
uv run scripts/wiki_interest.py report /tmp/wiki-reports/astronomy --note "Finding…" --note "Recommendation…"
uv run --with "matplotlib>=3.8,<4" python -m unittest discover -s tests   # offline tests
bash evals/run.sh                             # full scenarios on Claude Haiku 4.5 (needs the claude CLI)
```

Requirements: `uv` (it installs the exact versions pinned in `scripts/wiki_interest.py.lock`), or Python ≥ 3.10
with `pip install "matplotlib>=3.8,<4"`. No API keys needed. Wikimedia asks for contact info in the User-Agent:
`export WIKI_UA="my-app/1.0 (me@example.com)"`. There are no compiled files.

Each `study` writes `report.pdf` (one A4 page), `chart.png`, `results.json` (all metrics) and `series.csv`.
It prints a compact Markdown summary for the agent.

## Design

**The script computes, the agent interprets.** Cheap models make arithmetic and statistics mistakes, so every
number comes from code. The agent's job is to frame the question, pick articles, read the output against the
SKILL.md gotchas, and write the conclusions.

What the code does, and why:

| Problem | Solution |
|---|---|
| The same topic has a different title in each language | Topic → Wikidata item → article in each language (`resolve`). `search` finds the article when none is linked |
| Renamed articles split their views | Views of the article and all its redirects are summed |
| One viral day looks like growth | Main number = change in **median** daily views ("typical-day Δ"), shown next to total Δ, top-7-day share and spike dates |
| Seasonality (school year, New Year diets) | Default 24 months: last 12 compared with first 12, so the same months are compared |
| All of Wikipedia is losing traffic (2024–26) | "vs wiki Δ" divides by the change in the whole language edition's traffic |
| Wikis differ in size (es ≫ uk) | "Per 1M views" = views per million pageviews of that wiki, comparable across languages |
| "How much can we trust this?" | Mann-Kendall trend test + confidence (high/medium/low) with a flag that explains each downgrade |
| Cheap models misread ties and proxies, and re-rank by their own judgment | Script prints ranking chains with `≈` for ties, verdict words in table cells, `SUGGESTED TIERS` from a stated rule (`--rank-by relative|audience`), and marks proxy articles `*` |
| An auto-linked stub looks like a niche | `STUB?` warning when per-1M is < 10% of the other languages' median; the stub is left out of rankings |
| The control topic gets recommended | `--control` topics are compared, never tiered as candidates |
| Repeated and related questions | Disk cache (past pageviews never change): follow-ups cost no API calls. `report` re-renders the PDF without refetching |

## How I checked the AI-written code and skill

1. **Real API probes first.** I checked endpoints, title encoding, and 404 behavior against live data before
   writing the client. The first probe already found that Polish Wikipedia has no article on intermittent
   fasting. That became the MISSING/proxy flow.
2. **Unit tests on synthetic series** with known answers: steady growth, one spike, growth that only follows wiki
   traffic, low volume, short period, no data. A test caught a real bug: a single 50× spike gave "+13% growing"
   without a flag. The spike rule was fixed.
3. **Visual check** of every PDF layout change (rendered to PNG and inspected).
4. **Six rounds of end-to-end evals on Claude Haiku 4.5**, in an isolated workspace with only this skill
   installed, on the 3 task prompts plus a follow-up. I read full tool-call traces, not only final answers. Each
   failure became a gotcha, a template change, or (when prose was not enough) a script change. The
   log is in `evals/checks.md`. Examples: Haiku ranked Spanish first by raw views (fixed with the Per 1M column),
   called +2% "the only growing audience" (fixed with ties and verdict words printed by the script), converted
   886/day into "890k/month" (fixed with a no-arithmetic rule), and compared Polish "Post", which peaks on Good
   Friday (religious fasting), with Czech "intermittent fasting" (fixed by marking proxies and excluding them
   from size rankings). Final runs: 5–9 turns and $0.04–0.09 per question.
5. **Spec validation:** `skills-ref validate` passes.

Known gap: Haiku sometimes still writes country names or flags for language editions (check 8).

### Latest verification (2026-09-26)

A second pass used AI reviewers and evals against each other, and every claim below was checked by rerunning:

- **Audits.** Three independent AI audits ran: skill instructions against the code, a correctness audit with
  about 150 edge cases, and the pageview calls against the
  [Analytics API docs](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/). Every finding was
  reproduced before it was fixed. Fixes include: requests one at a time (API access policy), `Retry-After` on
  HTTP 429, the MISSING hint naming its topic, `--control` topics never recommended, a false "spike-driven" flag
  near ±10%, and new flags for new or mid-period articles.
- **With vs without the skill** (Sonnet 5, 4 tasks × 2 runs, graded against pass/fail criteria written before
  the runs, in `evals/evals.json`): 98% of checks passed with the skill vs 47% without, in about half the time.
  The baseline runs also found a real bug: a Wikidata sitelink can point at a *redirect*. German "Generative
  künstliche Intelligenz" redirects to "Generatives KI-Modell", so the skill measured 4 views/day instead of 66.
  Sitelinks are now followed to the article. Two more rounds after fixes: 88%, then 91%, with stricter grading.
- **Triggering** (`evals/trigger_eval.json`, 10 should-trigger and 10 near-miss prompts × 3 runs, run one at a
  time): 30/30 triggered, 0/30 false triggers. Parallel runs gave misleading low numbers (timeouts counted
  as misses).
- **Full scenario on Claude Haiku 4.5** (`evals/run.sh`, the three task prompts, v11 in `evals/checks.md`): all
  three answered with a PDF in 5–10 turns and $0.05–0.10 each. It surfaced one more skill bug, now fixed:
  control topics printed SUGGESTED TIERS, and Haiku recommended audiences from a control row.
- **Offline:** 32 unit tests pass, and `agentskills validate` passes.

Known gaps (Haiku prose): it sometimes writes country flags or names for language editions, calls a flat +2%
"the only growing one", or rewrites the ANSWER TABLE instead of pasting it. The script already prints the right
words and tables; the remaining fix is a stricter answer check (see Roadmap).

## Roadmap: toward complex research and bigger data

Each step is driven by evals. Add the new question types to `evals/prompts.txt` and `checks.md` first, then
change the skill until they pass.

1. **Topics as article sets, not single articles.** Expand a topic through Wikidata (subclass of / part of /
   main subject) or categories. Aggregate with per-article weights, and show which articles drive the change.
   Proxies then become measurable coverage rather than a manual judgment.
2. **Bigger data.** The per-article REST API allows about one article per request. For hundreds of articles × dozens
   of languages, switch to Wikimedia pageview dumps (monthly/hourly) loaded into DuckDB/Parquet. Move the cache
   from JSON files to that store. Add async fetching with a rate limiter. Use the `top` endpoints to discover
   trending topics instead of only checking known ones.
3. **Stronger statistics.** STL seasonal decomposition, change-point detection ("when did it start falling?"),
   bootstrap confidence intervals for growth, and short forecasts with intervals. Confidence then becomes an
   interval rather than a label.
4. **Better denominators.** Wikimedia's pageviews-by-country dataset turns "language" into "country" where
   needed. Readers who use English Wikipedia instead of their own edition should be modeled. Speaker or
   internet-user counts could be added as a labeled outside source.
5. **Answer checker.** A small script that checks the agent's final reply against `results.json` (pasted table,
   no country names, flat words for |Δ| < 10%, every number present in the output) and asks for a rewrite on
   failure. It turns the remaining prose gaps into a deterministic check.
6. **Triangulation.** Add other signals (Google Trends, edit activity, app-store and search data) behind the same
   `study` interface, and flag disagreement between sources as a trust signal.
6. **Research memory.** A `study.json` that records assumptions (criteria, proxies, period) across follow-ups, and a
   `diff` command ("what changed after adding German?"), so long multi-turn studies stay consistent.
7. **Evals at scale.** Automate grading of `checks.md` (regex + LLM judge), run in CI on several cheap models,
   and add trigger evals for the `description` (should and should-not activate prompts).
8. **Reports.** Localized report templates (the user's language), multi-page appendix, and a shareable HTML version.
