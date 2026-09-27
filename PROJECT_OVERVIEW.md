# Project overview: genesis_pes_task

Snapshot as of 2026-09-27.

## 1. What it is

The repo holds a single **Agent Skill** called `wiki-interest-research`. It measures public interest in topics
across Wikipedia language editions using Wikimedia pageview data. Its target users are B2C founders deciding
which topic or language audience to go after next. For each question it produces trust-scored metrics, a
chart and a one-page PDF.

Core design rule: **the script computes, the agent interprets.** Every number comes from the Python code. The
agent frames the question, picks the articles and writes the conclusions.

## 2. Layout

```
genesis_pes_task/
├── README.md                       pointer to the skill's README
├── .gitignore                      wiki-reports/, __pycache__/
├── .claude/skills/
│   └── wiki-interest-research  →   symlink to ../../.agents/skills/wiki-interest-research
└── .agents/skills/wiki-interest-research/     ← the skill (self-contained)
    ├── SKILL.md                    agent instructions: workflow, recipes, gotchas, answer template (v1.5)
    ├── README.md                   design, verification process, roadmap
    ├── .gitignore                  .cache/, __pycache__/
    ├── scripts/
    │   ├── wiki_interest.py        CLI entry point (resolve | search | study | report)
│   ├── wiki_interest.py.lock   uv lockfile for the script's PEP 723 deps
    │   ├── wikiapi.py              MediaWiki / Wikidata / Pageviews clients + on-disk JSON cache
    │   ├── analysis.py             metrics, Mann-Kendall trend test, confidence and flags (pure functions)
    │   └── report.py               chart PNG, one-page PDF, Markdown summary, rankings, suggested tiers
    ├── references/methodology.md   metric definitions and limitations (loaded on demand)
    ├── tests/
    │   ├── test_analysis.py        metrics on synthetic series (growth, spike, low volume, …)
    │   └── test_io.py              cache, CLI parsing, tier rule
    ├── evals/
    │   ├── run.sh                  runs prompts headless via `claude -p` (default: Haiku 4.5)
    │   ├── prompts.txt             3 task prompts (in Ukrainian)
│   ├── evals.json              graded eval cases (prompt + expected output)
│   ├── trigger_eval.json       should-trigger / should-not-trigger queries
    │   └── checks.md               grading checklist + history of fixes
    └── .cache/                     409 cached API responses, ~24 MB (git-ignored)
```

Why the symlink: VS Code / Copilot looks for skills under `.agents/skills/`, and Claude Code looks under
`.claude/skills/`. The symlink lets both find the same folder.

Size: about 1,500 lines of Python and Markdown in total.

## 3. The CLI (`scripts/wiki_interest.py`)

| Command   | Does |
|-----------|------|
| `resolve` | English title or Wikidata QID → the matching article in each language |
| `search`  | Searches article titles in one language edition (used when an article is `MISSING`) |
| `study`   | Fetches data, analyzes it, writes the chart and PDF. Outputs `report.pdf`, `chart.png`, `results.json`, `series.csv` |
| `report`  | Re-renders the PDF with a new title or notes, without fetching again |

Key flags: `--topic`, `--langs`, `--months 24`, `--start/--end`, `--article "Topic=pl:Title"`,
`--rank-by relative|audience`, `--out`.

Run it with `uv run` (matplotlib dependency is pinned in the PEP 723 script header). No API keys needed.

```bash
uv run scripts/wiki_interest.py study --topic "Astronomy" --topic "Physics" --langs uk \
  --question "Is interest in astronomy growing?" --out wiki-reports/astronomy
uv run --with "matplotlib>=3.8,<4" python -m unittest discover -s tests
```

## 4. Metrics produced

| Metric        | Meaning |
|---------------|---------|
| Views/day     | Absolute audience (article + all its redirects) |
| Per 1M views  | Views per million pageviews of that wiki. Use this to compare languages |
| Typical-day Δ | Change in median daily views, last 12 months vs first 12. Main growth number, resistant to spikes |
| Total Δ       | Change including spikes. A big gap from typical-day Δ means a few days drove it |
| vs wiki Δ     | Growth with the whole wiki's traffic trend removed |
| Trend p       | Mann-Kendall p-value (< 0.10 = consistent direction) |
| Confidence    | high / medium / low, with a flag explaining each downgrade |
| Rankings / SUGGESTED TIERS | Ordering with `≈` for ties; explore now / watch / skip, by a stated rule |

## 5. How it was verified

1. Probed the live APIs before writing the client code.
2. Unit tests on synthetic series with known answers. They caught a real bug where a single spike showed up
   as "growing".
3. Visual check of every PDF layout change.
4. Six rounds of end-to-end evals on Haiku 4.5. Each failure led to a gotcha, a template change or a script
   change. Final runs took 5–9 turns and cost $0.04–0.09 per question.
5. `skills-ref validate` passes.

Known gap: Haiku sometimes still writes country names or flags for language editions (eval check 8).

## 6. Roadmap (from the skill README)

1. Treat topics as sets of articles (Wikidata / categories) instead of single articles
2. Bigger data: pageview dumps loaded into DuckDB/Parquet, async fetching
3. Stronger statistics: STL decomposition, change-points, bootstrap confidence intervals, forecasts
4. Better denominators: pageviews by country, English-Wikipedia readers
5. Triangulation with other signals (Google Trends, edit activity)
6. Research memory: `study.json` plus a `diff` command
7. Automated eval grading in CI
8. Localized and HTML reports

## 7. Housekeeping notes

- `.cache/` (24 MB), `.ruff_cache/`, `wiki-reports/` and `.claude/wiki-interest-research-workspace/` are git-ignored.
