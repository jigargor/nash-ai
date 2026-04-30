# SEO Baseline Workflow (GSC + GA4)

Use this checklist before changing metadata, canonicals, internal links, or page copy.

## 1) Capture opportunity cohort (Search Console)

1. Open Google Search Console for the production property.
2. Go to **Performance > Search results**.
3. Set date range to **Last 28 days**.
4. Enable metrics: **Clicks, Impressions, CTR, Average position**.
5. Filter to page paths you can safely edit in this app.
6. Export top candidates where:
   - impressions are meaningful for the site,
   - CTR is below site median for similar positions,
   - average position is approximately 4-20.
7. Save the shortlist to `baseline-opportunity-template.csv`.

## 2) Capture behavior baseline (GA4)

1. Open GA4 and segment by the same landing-page paths.
2. Capture for each path:
   - sessions,
   - engagement rate,
   - conversion event counts (if configured),
   - bounce/engaged-session quality proxies used by your team.
3. Add values into the same CSV file in the `ga4_*` columns.

## 3) Freeze and compare windows

- **T0**: right before deploying SEO changes.
- **T+2w**: early movement check.
- **T+4w**: initial signal confirmation.
- **T+8w**: trend confirmation and next-iteration planning.

Do not treat day-to-day volatility as outcome proof; evaluate by cohorts over multi-week windows.
