# MyStocks - Build Progress

## Overall Status: Stage 6.9 - Complete ✅

---

## Stage 1: Project Foundation & Models
**Status:** ✅ Complete

- [x] Initialize Django project and `portfolio` app
- [x] Set up virtual environment and requirements.txt
- [x] Configure settings (SQLite, static files, templates)
- [x] Implement models: Ticker, Portfolio, Lot
- [x] Create migrations and seed sample data
- [x] Set up Django admin
- [x] Add base template with Bootstrap 5 layout
- [x] Write model unit tests (16 tests, all passing)

---

## Stage 2: Portfolio Management UI
**Status:** ✅ Complete

- [x] Portfolio list view (card grid with summary stats)
- [x] Portfolio detail view (holdings table with expandable lots per ticker)
- [x] Add/Edit/Delete Portfolio (HTMX modals)
- [x] Add/Edit/Delete Lot (HTMX modals with ticker autocomplete)
- [x] Portfolio summary calculations (cost basis, market value, gain/loss, %)
- [x] Holdings grouped by ticker with expandable lot rows
- [x] Responsive design
- [x] HTMX-powered interactions (no full page reloads)
- [x] Flash messages
- [x] Ticker search API endpoint
- [x] 35 tests, all passing

---

## Stage 3: Market Data & Price Charts
**Status:** ✅ Complete

- [x] Create `market` app with StockDataService
- [x] StockDataService (yfinance wrapper: quotes, history, company info)
- [x] PriceHistory model (OHLCV cache in SQLite)
- [x] Extended Ticker model with stats (day_change, market_cap, P/E, 52-week range, etc.)
- [x] Ticker detail page with Chart.js line chart
- [x] Key stats card (P/E, market cap, 52-week range, volume, dividend yield)
- [x] Time range selector (1W, 1M, 3M, 6M, 1Y, 5Y) with dynamic chart updates
- [x] Chart data JSON API endpoint
- [x] `refresh_prices` management command (single or all tickers)
- [x] Refresh button on ticker detail page (HTMX)
- [x] "Refresh Prices" button on portfolio detail page
- [x] Ticker symbols in holdings table link to ticker detail
- [x] Error handling with logging
- [x] 52 tests, all passing

---

## Stage 4: Technical Indicators & Scoring
**Status:** ✅ Complete

- [x] Create `analysis` app with IndicatorSnapshot model
- [x] TechnicalIndicatorService (RSI 14, MACD 12/26/9, Bollinger Bands 20/2, SMA 50/200, Volume ratio)
- [x] Signal generation per indicator (buy/hold/sell)
- [x] Composite Opportunity Score (0-100) with weighted formula: RSI(20%), MACD(20%), BB(20%), SMA(25%), Volume(15%)
- [x] Indicator cards section on ticker detail page with color-coded signal badges
- [x] Opportunity score badge in ticker header
- [x] Score column in holdings table (green >=70, yellow 40-69, red <40)
- [x] Chart overlays (SMA 50, SMA 200, Bollinger Bands) with toggle buttons
- [x] Indicator computation integrated into refresh_ticker flow
- [x] Admin registration for IndicatorSnapshot
- [x] 69 tests, all passing (17 new analysis tests)

---

## Stage 5: News & AI Sentiment Analysis
**Status:** ✅ Complete

- [x] NewsArticle model (title, url, source, published_at, sentiment_score, sentiment_label)
- [x] NewsService with yfinance news fetching and deduplication
- [x] VADER sentiment analysis on headlines (positive/neutral/negative with compound score)
- [x] 7-day rolling aggregate sentiment per ticker
- [x] Sentiment integrated into Opportunity Score (new weights: RSI 15%, MACD 15%, BB 15%, SMA 25%, Vol 10%, Sentiment 20%)
- [x] News feed section on ticker detail page with sentiment badges
- [x] Top-level News page (`/news/`) showing articles across all portfolio tickers
- [x] Settings page (`/settings/`) with VADER info and placeholder for OpenAI
- [x] Sentiment card added to technical indicators section
- [x] News and Settings sidebar links enabled
- [x] Admin registration for NewsArticle
- [x] 84 tests, all passing (15 new news/sentiment tests)

---

## Stage 6: Buying Opportunity Dashboard
**Status:** ✅ Complete

- [x] Opportunities dashboard (`/opportunities/`) ranked by opportunity score
- [x] Radar chart (Chart.js) showing sub-score breakdown per ticker (RSI, MACD, BB, SMA, Vol, Sentiment)
- [x] Quick-action "Add Lot" dropdown button on opportunities page (links to lot_create with ticker pre-selected)
- [x] WatchlistItem model (OneToOne to Ticker, with notes and added_at)
- [x] Watchlist page (`/watchlist/`) with add/remove functionality and HTMX interactions
- [x] Comparison view (`/compare/?symbols=AAPL,MSFT`) with side-by-side metrics and overlaid radar chart
- [x] Filter/sort controls on opportunities page (signal type, sector, sort by score/change/name)
- [x] Summary cards on opportunities page (total scored, buy/hold/sell counts, avg score)
- [x] Refresh_all updated to include watchlist tickers
- [x] Opportunities and Watchlist sidebar links enabled
- [x] Admin registration for WatchlistItem
- [x] 107 tests, all passing (23 new tests)
- Deferred to Stage 7: alerts system, historical opportunity tracking

---

## Stage 6.5: RSS Feed Integration
**Status:** ✅ Complete

- [x] RSSFeedSource model (name, url, category stock/geopolitical, enabled, last_fetched)
- [x] Updated NewsArticle model (nullable ticker for general news, feed_source FK, unique URL constraint)
- [x] Data migration seeding 7 default RSS feeds (CNBC Markets, CNBC Economy, MarketWatch, Investing.com, Seeking Alpha, BBC World, Al Jazeera)
- [x] RSSNewsService class (fetch_feed, fetch_all_feeds, match_ticker with whole-word symbol matching)
- [x] RSS feeds fetched automatically during refresh_all flow
- [x] Blended sentiment scoring (70% ticker-specific + 30% market-wide RSS sentiment)
- [x] News feed page with category filter tabs (All / Stock / Geopolitical / Per-Ticker)
- [x] Settings page with RSS feed management (enable/disable feeds via HTMX toggle)
- [x] Admin registration for RSSFeedSource
- [x] Toggle feed API endpoint
- [x] 132 tests, all passing (25 new tests)

---

## Stage 6.6: Branding, Auth & LLM Integration
**Status:** ✅ Complete

- [x] Renamed "MyStocks" to "ApexKube Capital" across all templates and branding
- [x] Moved "How Metrics Work" link to sidebar navigation
- [x] LLM stock analysis integration via Ollama (llama3.2:1b)
- [x] On-demand "Ask Kevin" AI analysis button per ticker
- [x] AIAnalysis model with prompt hashing to skip unchanged analysis
- [x] Login requirement via Django's LoginRequiredMiddleware
- [x] LoggedInTestCase base class across all test files
- [x] 148 tests, all passing

---

## Stage 6.7: Email Reports & Scheduling
**Status:** ✅ Complete

- [x] Email Report button in sidebar (HTMX with spinner)
- [x] Rich HTML email template with inline CSS, dark theme, table-based layout
- [x] Matplotlib chart generation (allocation pie, gain/loss bars, price sparklines, opportunity scores)
- [x] CID-attached inline images via manual MIME construction (Django 6.0 compatible)
- [x] Gmail SMTP integration with App Password authentication
- [x] Data refresh before report generation (quotes, indicators, news, AI analysis)
- [x] ReportAuditLog model tracking sent_at, recipient, status, error_message, ticker/portfolio counts
- [x] Audit Log page accessible from sidebar
- [x] Timezone changed to US/Eastern with timezone-aware report timestamps
- [x] ReportSchedule model with per-day booleans (Mon-Fri), time field, enabled toggle
- [x] Schedule management UI on Settings page (add/edit/delete/toggle via HTMX)
- [x] `check_report_schedules` long-running management command (container-friendly, no cron needed)
- [x] 178 tests, all passing

---

## Stage 6.8: PostgreSQL & Docker
**Status:** ✅ Complete

- [x] Migrated from SQLite to PostgreSQL (`psycopg` 3.x driver)
- [x] Database config via env vars (`DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`)
- [x] Created PostgreSQL user `mystocks` and database `mystocks`
- [x] Dockerfile with `python:3.14-slim`, gunicorn, collectstatic
- [x] All 178 tests passing on PostgreSQL

---

## Stage 6.9: Streamlined Weekly Report
**Status:** ✅ Complete

- [x] Simplified `gather_report_data()` — portfolio-level summaries only, removed per-holding breakdowns
- [x] Added `get_top_picks()` — selects top 5 tickers by opportunity score across portfolios + watchlist
- [x] Each pick includes ticker info, price, opportunity score, signal summary, and AI analysis
- [x] Updated `ReportChartService` — removed gain/loss bar chart and sparklines, added `generate_top_picks_chart()`
- [x] Redesigned `email_report.html` — two-section layout: portfolio performance + top 5 best buys
- [x] Removed per-holding detail rows (sparklines, per-ticker news, per-ticker AI analysis)
- [x] Updated email subject to weekly branding ("ApexKube Capital — Weekly Report")
- [x] Refresh now includes watchlist tickers alongside portfolio tickers
- [x] Updated tests — 7 new tests (top picks selection, limits, watchlist inclusion, chart generation)
- [x] 237 tests, all passing

---

## Stage 7: Polish, Performance & Deployment
**Status:** ⬜ Not Started

- [ ] Dark mode toggle
- [ ] Dashboard homepage widgets
- [ ] Loading states / skeleton screens
- [ ] Error pages (404, 500)
- [ ] Performance optimization (queries, caching)
- [ ] Comprehensive test suite
- [ ] Management commands (data refresh, cleanup)
- [ ] Docker support
- [ ] Production settings
- [ ] Final README update

---

## Change Log

| Date | Stage | Change |
|------|-------|--------|
| 2026-02-21 | — | Initial plan created |
| 2026-02-21 | 1 | Stage 1 complete: Django project, models, admin, base template, 16 tests passing |
| 2026-02-21 | 2 | Stage 2 complete: Full CRUD for portfolios & lots, HTMX modals, holdings table, 35 tests passing |
| 2026-02-21 | 3 | Stage 3 complete: Market data via yfinance, Chart.js charts, ticker detail page, refresh commands, 52 tests passing |
| 2026-02-21 | 4 | Stage 4 complete: Technical indicators (RSI, MACD, BB, SMA, Volume), opportunity scoring, chart overlays, 69 tests passing |
| 2026-02-21 | 5 | Stage 5 complete: News fetching via yfinance, VADER sentiment analysis, sentiment in opportunity score, news feed pages, settings page, 84 tests passing |
| 2026-02-21 | 6 | Stage 6 complete: Opportunities dashboard with radar charts, watchlist, comparison view, filter/sort, 107 tests passing |
| 2026-02-22 | 6.5 | RSS feed integration: 7 RSS sources, category filters, blended sentiment, feed management, 132 tests passing |
| 2026-02-22 | 6.6 | Branding, auth & LLM: Renamed to ApexKube Capital, login required, Ollama AI analysis, 148 tests passing |
| 2026-02-22 | 6.7 | Email reports & scheduling: HTML email with charts, audit log, report schedules on Settings page, cron command, 178 tests passing |
| 2026-02-23 | 6.8 | PostgreSQL migration, Dockerfile with gunicorn, env-var config, 178 tests passing on PostgreSQL |
| 2026-03-25 | 6.9 | Streamlined weekly report: portfolio performance summary + top 5 best buys, removed per-holding detail, 237 tests passing |
