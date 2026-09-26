# Eval checks

Run `evals/run.sh` (default model: Claude Haiku 4.5) and grade each transcript against these checks. Every
check comes from a real failure seen during development. When the agent makes a new kind of mistake, add a check
here and a fix to SKILL.md or the script.

| # | Check | Fails when |
|---|---|---|
| 1 | Uses the script for every number | agent writes its own analysis code or calls the APIs directly |
| 2 | ≤ 1 failed command | argument errors (e.g. wrong `--langs` format) cost extra turns |
| 3 | MISSING resolved with a same-concept article, or reported as "no data" | a broader proxy is compared on size, or a missing article is sold as a "niche" |
| 4 | Languages compared by Per 1M views and vs wiki Δ | raw views/day used to rank languages |
| 5 | \|Δ\| < 10% called flat; ties from the `≈` chains respected | "+2% = the only growing audience" |
| 6 | Confidence reported with its reasons | confidence missing from the answer |
| 7 | No arithmetic or outside numbers presented as data | "886/day = 890k/month", speaker counts without a label |
| 8 | Language ≠ country | "Poland", "Ukraine market", country flags for a language edition |
| 9 | PDF has the agent's notes; answer follows the template and links report + chart | missing `report` step or file paths |
| 10 | Follow-up reruns `study` with changed flags; no refetch for detail questions | recomputes by hand or restarts from scratch |

## History (Claude Haiku 4.5, 3 prompts from prompts.txt + 1 follow-up)

| Round | Change | Result |
|---|---|---|
| v1 | first SKILL.md | works end-to-end (5–10 turns, $0.04–0.07). Fails 4, 3 (missing article = "niche"), 6, 8 |
| v2 | checklist, recipes, gotchas, answer template, control topic, Per 1M views column | 4 and 6 fixed. Fails 2 (`--langs a b`), 5, 7 |
| v3 | CLI accepts `--langs a b`; script prints flat/declining words; per-capita gotcha | 2 fixed. Follow-up (add languages, 36 months, size criterion) handled in 3 turns. Fails 5, 7 |
| v4 | script prints `≈` ranking chains; gotchas for arithmetic and hypotheses | 7 fixed. Fails 3 (Polish "Post" used as a same-size proxy) |
| v5–v6 | proxies (different Wikidata item) marked `*` and excluded from size ranking; verdict word inside table cells | 3 and 5 fixed. Remaining: 8 partly (country flags in a recommendation table) |
| v7 | code-review fixes; eval harness fix (`claude -p` read stdin, so each case got every prompt) | 3/3 prompts answered, PDFs produced, 4–10 turns, $0.035–0.08; follow-up in 3 turns. Pass: 1, 2, 3, 4, 8, 9, 10. Fails: 5 (case 3: "+2% = only positive"), 6 and 7 in the follow-up (confidence column dropped; "886/day × 2% conversion = 600–700 users") |
| v8 | script prints `SUGGESTED TIERS` (`--rank-by relative|audience`); README moved into the skill | 3/3 + follow-up, 3–9 turns, $0.05–0.09. Check 5 fixed: tiers copied exactly in case 3 and in the follow-up (which chose `--rank-by audience` itself). Fails: 3 partly (case 1 compares the Polish proxy's size, 50 vs 6/day, despite the `*` caveat), 6 and 7 in the follow-up (Confidence column dropped; "886+797 = 70% of all" is wrong: it is 60%), 8 (country flags) |
| v9 | proxy size cells printed as `n/a (proxy)`; script prints a ready ANSWER TABLE (with Confidence) | 3/3 + follow-up, 3–12 turns, $0.05–0.10. All 4 answers paste the ANSWER TABLE (check 6 fixed, including the follow-up); case 1 no longer compares the proxy's size (check 3 fixed); tiers copied exactly (check 5). Remaining, prose only: 7 (follow-up invents "-50% in an alternative scenario"; case 3 states "migration to Duolingo" as fact), 8 (country wording in the follow-up), "per capita" wording once |
| v10 | second code review: sitematrix language check, rankings across topics too, retries on timeouts, API errors not cached, cache fallback, isolated eval workspaces | No regression: 3/3 answered in isolated workspaces, 5–9 turns, $0.05–0.08; ANSWER TABLE and tiers copied exactly. Prose slips remain (case 3: "largest absolute interest" for the per-1M leader; "the only flat one" while pt/es are also flat) |
