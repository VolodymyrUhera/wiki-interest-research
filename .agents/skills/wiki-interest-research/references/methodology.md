# Methodology and how to read the numbers

Read this when the user asks "how confident is this", "why", or questions a number.

## Data

- Source: Wikimedia Analytics API, per-article daily pageviews, `agent=user` (known bots and spiders removed),
  `access=all-access` (desktop + mobile web + app). Data exists from 2015-07.
- Each series = one article in one language edition **plus all its redirects** (up to 50). Wikimedia counts
  views of a redirect title separately, so summing them gives the real reach of the article.
- Normalization: total user pageviews of the whole language edition (`aggregate` endpoint), monthly.
- Only complete calendar months are used. Default period: last 24 complete months.
- Requests go one at a time (Analytics API access policy); HTTP 429 honours `Retry-After`. Set `WIKI_UA` to put
  your contact info in the User-Agent, as Wikimedia's policy asks.
- Responses are cached in `.cache/` in the skill directory (or `$WIKI_CACHE_DIR`, or the user cache dir when the
  skill folder is read-only). Data older than 5 days is final and is cached
  forever. Newer data may still be loading, so it is cached for 1 hour only. Reruns and follow-up questions
  with the same articles and dates make no network calls. `--end` must be a complete month, and a missing
  whole-wiki month is flagged instead of counted as zero.

## Metrics (fields in results.json → metrics)

| Field | Meaning |
|---|---|
| `window` | Growth compares the last k months with the first k months of the period, k = min(12, months/2). With k = 12 the windows are whole years, so seasonality cancels out. |
| `growth_robust` ("Typical-day Δ") | Change in the **median** daily views between the windows. Main growth number: one viral day cannot move it. |
| `growth_total` ("Total Δ") | Change in total views. It includes spikes, so it is the "naive" number. |
| `growth_project` | Change in the whole wiki's traffic over the same windows. Many wikis are losing traffic (search answers, AI summaries). |
| `growth_normalized` ("vs wiki Δ") | `(1+growth_robust)/(1+growth_project) - 1`. Change in the topic's *share of attention* inside that language edition. Use it to compare languages. |
| `trend_annual_rate`, `trend_r2` | Log-linear fit on monthly totals: annualized growth rate and how well a straight trend explains the data. |
| `mann_kendall_p` ("Trend p") | Mann-Kendall test for a consistent monotonic monthly trend. p < 0.10 = consistent direction. |
| `top7_share` | Share of all views that fall on the 7 busiest days. High = attention comes in bursts (news, TV, viral links, bot bursts). |
| `spike_days` | Up to 3 days with views > 5× the median (and > 50). Useful to name the event behind a spike. |
| `avg_daily_last` ("Views/day") | Average daily views in the last window: the size of the audience. |
| `share_ppm_last` | Views per million pageviews of that wiki in the last window. Size of interest, comparable across languages. |
| `direction` | From `growth_robust`: growing (> +10%), declining (< -10%), otherwise flat. |

## Confidence rules

Start at **high**. Each problem below lowers it one step (very low volume lowers it two steps).
Result: 0 problems = high, 1 = medium, 2+ = low.

1. Low volume: < 20 views/day in the last window (< 5 counts as two problems). Small counts swing a lot.
2. Windows shorter than 12 months: seasonality not controlled (e.g. exam season, New Year diets).
3. Spike-driven: top 7 days > 20% of all views, or total and typical-day growth disagree (different
   direction with a gap over 5 points, or a ratio outside 0.8–1.25).
4. No consistent trend: Mann-Kendall p > 0.10.
5. The direction reverses after normalization (only when |typical-day Δ| > 10%): the topic "grows" only because
   the whole wiki grew, or "declines" only because the whole wiki declined.
6. Whole-wiki traffic missing for a month: vs wiki Δ is not computed.
7. Small starting base: < 20 views/day in the first window (but not the last): growth % is inflated.
8. Typical day was 0 in the first window (new or sparse article): no growth number (counts as two problems).
9. Typical day fell to 0 while total views changed less than 50%: bursty traffic, median unreliable.
10. No views in the first 30+ days (article created or renamed mid-period): growth is inflated.

Confidence is about the **data**. It does not say whether a business decision is right.

## Rankings, tiers and warnings

- Ties: sizes within 10% of each other, momentum within 10 points, are joined with `≈`.
- Tiers (`SUGGESTED TIERS`): "top half" = at least 50% of the largest size in the group. Low confidence = skip.
  Relative rule: top half and not declining vs wiki = explore now; bottom half and declining = skip; else watch.
  Audience rule (`--rank-by audience`): top half = explore now whatever the momentum.
- Proxies (`*`, article about a different Wikidata item) and `STUB?` series are left out of size rankings and
  tiers. `STUB?` = per-1M below 10% of the median of the other languages for the same topic.
- `--control` topics are compared across languages but never ranked as candidates among topics.

## Known limitations (tell the user when relevant)

- Pageviews measure attention, not demand or willingness to pay. Treat them as a signal for what to
  validate next, not as proof.
- One article is only a proxy for a topic. If the proxy is imperfect (no exact article, broader or narrower
  article), say so. Comparing 2–3 related articles makes the answer stronger.
- Languages are not countries: Spanish, English, Portuguese or Russian readers are spread across many
  countries, and many people read English Wikipedia instead of their own language edition.
- Wiki size differs a lot, so compare languages by growth and `share_ppm_last`, not by raw views.
- Article renames are handled through redirects. Article splits or merges inside the period are not.
- Automated traffic is only partly filtered. A sudden plateau at an unusually high level can be a bot.
