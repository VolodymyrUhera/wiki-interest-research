---
name: wiki-interest-research
description: Measures and compares public interest in topics across Wikipedia language editions from Wikimedia pageview data, with a trust assessment, charts and a shareable one-page PDF. Use when someone asks whether interest in a topic is growing, compares topics or language audiences, decides which course, topic, language or localization to invest in next, or asks how much a trend can be trusted, even when Wikipedia is not named (pageviews, audience interest, demand signals, localization or market research by language). E.g. "compare interest in intermittent fasting in Polish vs Czech Wikipedia", "is astronomy growing in Ukrainian Wikipedia?", "which language should we localize our course into next?". Not for editing Wikipedia, looking up facts from articles, or web-search traffic (Google Trends).
compatibility: Needs uv (or Python 3.10+ with matplotlib) and internet access to wikipedia.org, wikidata.org and wikimedia.org.
metadata:
  version: "1.5"
---

# Wikipedia interest research

`scripts/wiki_interest.py` does all data work: it finds the article in each language, sums views of the article and
its redirects, normalizes by whole-wiki traffic, scores trust, and draws the chart and PDF. **Never compute numbers
yourself or call the APIs directly.** Run the script and interpret its output.

`$SKILL` = the directory that contains this file. Run commands from the user's working directory, so reports are
saved there. The first `uv run` installs matplotlib (a few seconds).

```bash
uv run $SKILL/scripts/wiki_interest.py study --topic "Astronomy" --control "Physics" --langs uk \
  --question "<user's question, verbatim>" --out wiki-reports/<short-slug>      # fetch + analyze + chart + PDF
uv run $SKILL/scripts/wiki_interest.py search "<words in that language>" --lang pl   # find an article title
uv run $SKILL/scripts/wiki_interest.py report wiki-reports/<short-slug> --title "..." --note "..." --note "..."
```

## Workflow

Copy this checklist and tick it off:

- [ ] 1. Frame: topics, wiki codes, period, and **the user's criterion for "promising"** (see Recipes)
- [ ] 2. Choose articles (proxies) and a control topic
- [ ] 3. Run `study` (`--langs` takes `pl,cs` or `pl cs`)
- [ ] 4. Handle every `MISSING` and `STUB?` line
- [ ] 5. Self-check the interpretation against **Gotchas**
- [ ] 6. Write findings into the PDF with `report`
- [ ] 7. Answer using the **Answer template**

**Step 1 – Frame.** Wiki codes, not country codes: uk (Ukrainian), cs (Czech), pl, de, es, pt, tr, ... Period: last
24 complete months by default (`--months 24`). Use 24 or more, so year-over-year comparison cancels seasonality.
Exact months: `--start 2023-01 --end 2025-12`.

**Step 2 – Choose articles.** `--topic` takes the **English** article title, a Wikidata QID, or a title in another
language with `--source-lang xx`. The script finds
the same article in every language. For a broad theme, choose the 1–2 most central articles (e.g. "learning
English" → "English language", "English as a second or foreign language"). When the question is "is this
growing?", add a **control topic** from the same field with `--control` (Astronomy → Physics; Intermittent
fasting → Dieting). The control shows whether a change is specific to the topic or affects the whole field. Pass it
with `--control`, not `--topic`, so it never shows up as a candidate in topic tiers.

**Step 4 – MISSING and STUB?.**

- **MISSING** = no article in that language is linked to the topic. Search with words **in that language** (not
  English or the user's language), pick the closest article, and rerun with the `--article "Topic=pl:Exact Title"`
  the MISSING line prints (`Topic` = exactly the `--topic`/`--control` value). Accept only an article about the
  **same concept**. A broader article measures something else: Polish "Post" (fasting in general) used for
  intermittent fasting peaks on Good Friday, because it measures religious fasting. Skip such an article, or use it
  only for the trend. If nothing fits, report "no data for this language". Do not call it an opportunity.
- **STUB?** = the linked article has under 10% of the per-1M interest the same topic has in other languages: likely
  a stub or side page, not a niche. The script already leaves it out of rankings and tiers. Search as for MISSING;
  if a better article exists, rerun with `--article`. Otherwise keep it and name the warning in Caveats.
- An `--article` replacement about a different Wikidata item is marked `*` (proxy): compare its trend only, never
  its size. Name every proxy in the answer.

**Step 6 – Report.** 3–6 notes in the user's language: the answer, the key numbers, the recommendation with the
criterion behind it, and the main caveat. `report` only re-renders the PDF (no refetch, about 2 s). Each `report`
call replaces all earlier notes, so pass the full set every time.

## Recipes by question type

- **"Is X growing, and can we trust it?"** Direction = typical-day Δ. Trust = the Confidence column plus its flags,
  plus the control topic: if the control falls just as much, the decline is not about X. Quote Trend p and
  Views/day as the evidence.
- **"Compare X in language A vs B."** Compare **vs wiki Δ** (momentum) and **Per 1M views** (relative size).
- **"Which audiences or languages next?" / "Which topic next?"** The script prints `SUGGESTED TIERS`
  (explore now / watch / skip, each with its reason). **Copy them as they are and state the rule shown.** Default
  rule: relative interest (Per 1M views) first, then momentum. If the user says audience size matters more, rerun
  with `--rank-by audience`. For any other criterion, apply it yourself and say that you changed the rule.
  Do not use stars, invented scores or launch dates.
- **Follow-ups** ("add German", "use 3 years", "size matters more"): rerun `study` with the changed flags and a
  new `--out`, then answer with the full template again, including the new ANSWER TABLE. For a specific month,
  read `series.csv` (monthly values only); for spikes, `results.json` → `metrics.spike_days` (top 3 days). Daily
  data is not saved.

## Reading the output

The output starts with an **ANSWER TABLE** to paste into your reply, then a Details table.

| Column | Use it for |
|---|---|
| Views/day | Absolute audience size. Below 20 = noisy percentages. `n/a (proxy)` = not comparable, never estimate it |
| Per 1M views | Relative interest: views per million pageviews of that wiki. **Compare languages with this** |
| Typical-day Δ | Main growth number (median day, last k vs first k months; k = 12 at 24+ months, see header). Spike-resistant |
| Total Δ | Includes spikes. A large gap to typical-day Δ = driven by a few days, see `spikes` dates |
| vs wiki Δ | Growth after removing the whole wiki's trend. Momentum across languages |
| Trend p | < 0.10 = consistent direction over the period (raw views, so check vs wiki Δ too) |
| Confidence | high / medium / low. Each `flag:` line explains a downgrade: repeat them |
| Ranking lines | Languages ordered by relative interest and by momentum, `≈` = tie |
| SUGGESTED TIERS | explore now / watch / skip by the stated rule. Use for "which first" |
| CONTROL CHECK | Topic vs its control per language, on vs wiki Δ, gap already computed. Quote it; do not re-derive |

Other lines: `- <series>: ... [redirects N%; spikes DATE (views)]` summary per series, with `flag:` sub-lines ·
`*` after a label = proxy · `PROXY` / `STUB?` / `MISSING` = see Step 4 · `→ no clear leader` = top two tied ·
`not comparable` / `n/a` = too little data (or whole-wiki traffic missing) for that number.

For metric definitions and confidence rules, read [references/methodology.md](references/methodology.md) when the
user asks about method or trust, or when a number looks surprising.

## Gotchas

These are mistakes seen in real runs:

- **Raw views compare wiki sizes, not interest.** Spanish Wikipedia has far more readers than Ukrainian. When
  ranking languages, "most views/day" is not "most interest". Use Per 1M views (per million *pageviews of that
  wiki*, not per capita or per speaker).
- **|Δ| < 10% is flat.** Use the words the script prints ("flat vs wiki traffic"). +2% is "holding steady",
  never "growing" or "the only growing audience". Treat differences under ~10 points between series as ties.
- **Rankings: copy the `Ranking ...` lines.** `≈` means tie, so "tr +2% ≈ pt -5% ≈ es -8%" has no leader.
- **Do no arithmetic.** Quote numbers exactly as printed; do not convert views/day to monthly totals, sum
  series, or estimate users or revenue ("886/day × 2% conversion = 600 users" is invented). Need another number?
  Read `results.json`.
- **Explanations are hypotheses.** "Readers moved to Duolingo" is not in the data: write "possible reason:".
- **Most wikis lost traffic in 2024–2026.** A raw decline is normal. Judge a topic by vs wiki Δ and by the control
  topic before saying interest is falling. Why wikis lose traffic (AI answers, search changes) is not in this data:
  if you mention it, write "possible reason:".
- **A language is not a country or a market.** Say "Polish-language readers", not "Poland", and use no country
  flags. Spanish, Portuguese and English cover many countries, and many people read English Wikipedia instead of
  their own.
- **A missing or STUB? article is not a niche.** It means no usable data for that language, or that the article has
  another name.
- **Do not add outside numbers** (speaker counts, market size, prices) unless you label them as outside knowledge
  that is not from this data.
- **Seasonality and news:** name the dates from `spikes` and never present a spike as a trend. The cause is not in
  the data: write "possible reason: school year starts" (or New Year diets, exams, a news event), not a fact.
- Pageviews measure attention, not willingness to pay. Every recommendation should end with how to validate it
  (survey, landing-page test, search-volume check in that language).

## Answer template

Reply in the user's language:

```markdown
**Answer:** <1–2 sentences: direct answer + overall confidence>

<the ANSWER TABLE from the script output, pasted unchanged with every row, control rows included (translate only the header)>

**Why:** 2–4 bullets, each with numbers from the output (include the control topic if used)
**Recommendation:** <SUGGESTED TIERS as printed + the rule used>   ← only if the user asked what to do
**Caveats:** proxies used, STUB? warnings, every flag of each series you recommend, missing languages, and "attention ≠ demand"
**Next step:** <one concrete way to validate>
Report: <out>/report.pdf · Chart: <out>/chart.png
```

## Errors

- `no article '...' on en.wikipedia`: wrong `--topic` title. Run `search "..." --lang en` and use the exact title,
  or pass `--source-lang uk` with a title in that language.
- Every other `error:` line names its fix (unknown wiki code, incomplete `--end`, data before 2015-07, bad
  `--article`). Apply it once; do not retry the same command.
- Network errors are retried automatically. If they persist, tell the user that the Wikimedia API is unreachable.
- Without uv: `pip install "matplotlib>=3.8,<4"`, then run `python3 $SKILL/scripts/wiki_interest.py ...`.
