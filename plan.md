# MyStocks - Build Plan

## Overview
A Django-based stock portfolio analysis application that lets users manage stock positions with multiple lots, pull real-time market data, compute technical indicators, analyze news sentiment with AI, and surface buying opportunities.

**Tech Stack:**
- Backend: Python / Django 5.x
- Frontend: Django Templates + HTMX + Bootstrap 5 + Chart.js
- Database: SQLite
- Data Source: yfinance
- Technical Analysis: pandas / ta-lib (pure Python `ta` library)
- AI Sentiment: OpenAI API (or local model) for news headline scoring
- Task Scheduling: django-q2 (background data refresh)

---

## Stage 1: Project Foundation & Models
**Goal:** Django project scaffold, data models, and basic CRUD for portfolios.

### Tasks
- [ ] Initialize Django project (`mystocks_project`) and app (`portfolio`)
- [ ] Set up Python virtual environment and `requirements.txt`
- [ ] Configure settings (SQLite, static files, templates)
- [ ] Design and implement models:
  - `Ticker` — symbol, company name, sector, last_price, last_updated
  - `Portfolio` — name, created_at, notes
  - `Lot` — FK to Ticker, FK to Portfolio, shares, cost_basis, purchase_date, notes
- [ ] Create migrations and seed sample data
- [ ] Set up Django admin for all models
- [ ] Add base template with Bootstrap 5 layout (navbar, sidebar, footer)
- [ ] Write model unit tests

**Deliverables:** Working Django app with models, admin, and base layout.

---

## Stage 2: Portfolio Management UI
**Goal:** Full CRUD interface for managing portfolios, tickers, and lots.

### Tasks
- [ ] Portfolio list view — card grid showing each portfolio with summary stats
- [ ] Portfolio detail view — table of holdings grouped by ticker, with lots expandable
- [ ] Add/Edit/Delete Ticker to portfolio (modal forms via HTMX)
- [ ] Add/Edit/Delete Lot (inline form with date picker, shares, price)
- [ ] Portfolio summary calculations:
  - Total cost basis, current market value, total gain/loss ($ and %)
  - Per-ticker: avg cost, total shares, current value, gain/loss
  - Per-lot: individual gain/loss
- [ ] Responsive design — works on desktop and mobile
- [ ] HTMX-powered interactions (no full page reloads for add/edit/delete)
- [ ] Flash messages for user feedback (success, error)

**Deliverables:** Fully functional portfolio management with a polished UI.

---

## Stage 3: Market Data & Price Charts
**Goal:** Pull live stock data from yfinance and display interactive charts.

### Tasks
- [ ] Create `market` app for data fetching services
- [ ] `StockDataService` class — wraps yfinance for:
  - Current price, day change, volume
  - Historical OHLCV data (1d, 1w, 1m, 3m, 6m, 1y, 5y)
  - Company info (sector, market cap, P/E, dividend yield)
- [ ] `PriceHistory` model — cache historical prices in DB to reduce API calls
- [ ] Background data refresh via django-q2 scheduled tasks
- [ ] Ticker detail page with:
  - Price chart (Chart.js with candlestick or line chart)
  - Key stats card (P/E, market cap, 52-week range, volume)
  - Time range selector (1D, 1W, 1M, 3M, 6M, 1Y, 5Y)
- [ ] Portfolio dashboard — mini sparkline charts per holding
- [ ] API endpoint (Django REST or JSON views) for chart data
- [ ] Rate limiting / caching layer for yfinance calls
- [ ] Error handling for invalid tickers, API failures

**Deliverables:** Live price data, interactive charts, cached market data.

---

## Stage 4: Technical Indicators & Scoring
**Goal:** Compute RSI, MACD, Bollinger Bands, moving averages, and volume analysis; generate a composite buy/sell score.

### Tasks
- [ ] Create `analysis` app
- [ ] `TechnicalIndicatorService` class computing:
  - **RSI** (14-period) — oversold < 30, overbought > 70
  - **MACD** — signal line crossovers
  - **Bollinger Bands** — price relative to upper/lower bands
  - **Moving Averages** — 50-day and 200-day SMA, golden/death cross detection
  - **Volume Analysis** — volume vs 20-day average, unusual volume flags
- [ ] `IndicatorSnapshot` model — store latest indicator values per ticker
- [ ] Composite **Opportunity Score** (0-100):
  - Weighted combination of all indicators
  - Configurable weights via settings
- [ ] Ticker detail page — indicator cards with gauges/meters
- [ ] Indicator chart overlays (Bollinger Bands on price chart, RSI subplot, MACD subplot)
- [ ] Opportunity score badge on portfolio holdings table
- [ ] Color-coded signals: green (buy), yellow (hold), red (sell)
- [ ] Unit tests for indicator calculations

**Deliverables:** Technical analysis engine with visual indicators and scoring.

---

## Stage 5: News & AI Sentiment Analysis
**Goal:** Pull news for each ticker and use AI to score sentiment, integrated into opportunity scoring.

### Tasks
- [ ] `NewsService` class — fetch news via yfinance `.news` + optional RSS feeds
- [ ] `NewsArticle` model — title, url, source, published_date, ticker, sentiment_score
- [ ] AI Sentiment Analyzer:
  - Use OpenAI API (gpt-4o-mini) or local model to score headlines -1.0 to +1.0
  - Batch processing to minimize API calls
  - Cache sentiment scores in DB
  - Fallback: VADER sentiment (nltk) if no API key configured
- [ ] News feed on ticker detail page — cards with sentiment badges
- [ ] Aggregate sentiment score per ticker (rolling 7-day average)
- [ ] Integrate sentiment into Opportunity Score (configurable weight)
- [ ] News alerts — highlight strongly negative/positive news
- [ ] Settings page for AI API key configuration

**Deliverables:** News feed with AI-driven sentiment analysis integrated into scoring.

---

## Stage 6: Buying Opportunity Dashboard
**Goal:** A dedicated dashboard that ranks tickers by opportunity and helps users decide when to buy more.

### Tasks
- [ ] **Opportunities Dashboard** — top-level page showing:
  - Ranked list of portfolio tickers by Opportunity Score
  - Visual score breakdown (radar chart per ticker)
  - Quick-action "Add Lot" button for each opportunity
- [ ] **Watchlist** — add tickers not yet in portfolio to monitor
- [ ] **Alerts system:**
  - User-defined price alerts (price drops below X)
  - Score threshold alerts (opportunity score > 80)
  - Display in-app notification bell
- [ ] **Comparison view** — side-by-side comparison of 2-3 tickers
- [ ] **Historical opportunity tracking** — did past high-score moments predict gains?
- [ ] Filter/sort controls (by score, sector, gain/loss, etc.)

**Deliverables:** Actionable opportunity dashboard with alerts and watchlist.

---

## Stage 6.9: Streamlined Weekly Report
**Goal:** Redesign the email report to focus on overall portfolio performance and surface the top 5 best buying opportunities for the week.

### Current State
The report currently shows per-holding details (shares, avg cost, price, value, gain/loss, sparkline, technical signals, AI analysis, recent news) for every ticker in every portfolio — too much detail for a quick weekly read.

### Tasks
- [ ] **Simplify `gather_report_data()`** — collect only portfolio-level summaries (total cost, market value, gain/loss, gain/loss %) instead of per-holding breakdowns
- [ ] **Add top-5 best-buys selection** — across all portfolio + watchlist tickers, rank by opportunity score and select the top 5; for each, include:
  - Ticker symbol & company name
  - Current price & day change %
  - Opportunity score (0-100)
  - Signal summary (buy/hold/sell from RSI, MACD, BB, SMA, Volume, Sentiment, Options)
  - One-line AI analysis summary (Kevin's Take)
- [ ] **Update `ReportChartService`** — remove per-holding sparklines and gain/loss bar chart; keep portfolio allocation pie chart; replace opportunity score chart with a top-5-only version
- [ ] **Redesign `email_report.html`** — two-section layout:
  1. **Portfolio Performance** — summary cards (total cost, market value, gain/loss with %) and allocation pie chart per portfolio
  2. **Top 5 Best Buys This Week** — ranked table with score, signals, price, and AI take for the 5 highest-scoring tickers
- [ ] **Remove per-holding sections** — drop the detailed holdings table, per-ticker sparklines, per-ticker news, and per-ticker AI analysis rows from the email template
- [ ] **Update `generate_and_send()`** — adjust chart generation and image attachment logic for the new streamlined data
- [ ] **Update email subject** — change to "Weekly Report" style (e.g., "ApexKube Capital — Week of March 25, 2026")
- [ ] **Update tests** — adjust existing report tests for the new data structure and template; add test for top-5 selection logic

**Deliverables:** A concise weekly email showing portfolio health at a glance plus the 5 most compelling buy opportunities.

---

## Stage 6.10: CSV Export of Portfolio Holdings
**Goal:** Allow users to download their portfolio holdings as a CSV file from the portfolio detail page.

### Tasks
- [ ] **Add `export_portfolio_csv` view** in `portfolio/views.py` — accepts portfolio PK, returns an `HttpResponse` with `content_type='text/csv'` and `Content-Disposition: attachment; filename="<portfolio_name>_holdings.csv"`
- [ ] **CSV row structure** — grouped by ticker with a summary row followed by lot detail rows:
  - **Ticker summary row:** Ticker, Company Name, Sector, Total Shares, Avg Cost, Current Price, Day Change %, Total Value, Total Gain/Loss ($), Total Gain/Loss (%), Opportunity Score
  - **Lot detail rows (indented):** blank first column (or "  ↳"), "", "", Shares, Cost Basis, Purchase Date, Notes, Lot Value, Lot Gain/Loss ($), Lot Gain/Loss (%), ""
  - Use `get_holdings()` for ticker-level aggregates; iterate `h['lots']` for per-lot rows beneath each ticker
  - Look up `IndicatorSnapshot` per ticker for opportunity score
- [ ] **Add URL route** — `path('<int:pk>/export/', views.export_portfolio_csv, name='portfolio_export_csv')` in `portfolio/urls.py`
- [ ] **Add download button** to the portfolio detail page — a simple link/button (e.g., "Export CSV") next to the existing refresh button, pointing to the export URL
- [ ] **Write tests** — verify response content type, filename header, CSV row count matches holdings count, column values are correct, and 404 for nonexistent portfolio

**Deliverables:** One-click CSV download of holdings from any portfolio detail page.

---

## Stage 6.11: Multi-User Support & Registration
**Goal:** Make the app fully multi-tenant so each user sees only their own portfolios, watchlist, and report schedules. Add self-service account creation.

### Design Decisions
- **Tickers** remain global — shared market data, indicators, options snapshots, AI analysis, and news. No user FK needed.
- **Portfolios, WatchlistItems, ReportSchedules** become per-user via a `user` FK to `auth.User`.
- **Data migration** assigns all existing records to the first superuser account.
- **Admin** (Django superuser) can see all users' data via `/admin/`.

### Tasks

#### 6.11a: Model Changes & Data Migration
- [ ] **Add `user` FK to `Portfolio`** — `models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='portfolios')`
- [ ] **Add `user` FK to `WatchlistItem`** — same pattern, `related_name='watchlist_items'`; drop the `OneToOneField` on ticker (a ticker can now be on multiple users' watchlists) and replace with `ForeignKey` + `unique_together = ('user', 'ticker')`
- [ ] **Add `user` FK to `ReportSchedule`** — same pattern, `related_name='report_schedules'`
- [ ] **Data migration** — assign all existing Portfolio, WatchlistItem, and ReportSchedule rows to the first superuser (`User.objects.filter(is_superuser=True).first()`)

#### 6.11b: User Registration
- [ ] **Registration view** — simple form with username + password + password confirmation using Django's `UserCreationForm`
- [ ] **Registration template** — styled to match existing login page (dark theme, ApexKube branding)
- [ ] **Registration URL** — `accounts/register/` with a link from the login page ("Don't have an account? Sign up")
- [ ] **Auto-login after registration** — log the user in immediately after successful signup and redirect to dashboard

#### 6.11c: Query Scoping (Views)
- [ ] **Scope all Portfolio queries** — filter by `user=request.user` in: `dashboard`, `portfolio_list`, `portfolio_detail`, `portfolio_create` (set user on save), `portfolio_edit`, `portfolio_delete`, `portfolio_export_csv`, `portfolio_growth_data`
- [ ] **Scope WatchlistItem queries** — filter by `user=request.user` in all watchlist views; set user on create
- [ ] **Scope ReportSchedule queries** — filter by `user=request.user` in schedule CRUD views and `_render_schedule_list`
- [ ] **Scope report generation** — `EmailReportService` methods need to accept a user and filter portfolios/watchlist by that user
- [ ] **Scope opportunities/comparison** — filter tickers shown to those in the user's portfolios + watchlist
- [ ] **Ownership checks** — return 404 (not 403) if a user tries to access another user's portfolio/lot/schedule by PK, using `get_object_or_404(Portfolio, pk=pk, user=request.user)`

#### 6.11d: Report & Refresh Scoping
- [ ] **Update `refresh_portfolio_data()`** — accept a user parameter; only refresh tickers in that user's portfolios + watchlist
- [ ] **Update `gather_report_data()`** — accept a user parameter; only include that user's portfolios
- [ ] **Update `get_top_picks()`** — accept a user parameter; only consider that user's tickers
- [ ] **Update `check_report_schedules` command** — iterate all users' schedules and send per-user reports
- [ ] **Update `refresh_all` view** — only refresh tickers belonging to `request.user`'s portfolios + watchlist

#### 6.11e: Tests
- [ ] **Registration tests** — GET renders form, POST creates user and logs in, duplicate username rejected
- [ ] **Isolation tests** — user A cannot see user B's portfolios, watchlist items, or schedules (verify 404)
- [ ] **Scoping tests** — dashboard/list views only show current user's data
- [ ] **Migration test** — verify existing data is assigned to the first superuser
- [ ] **Update existing tests** — add `user=self.user` when creating Portfolio, WatchlistItem, ReportSchedule in setUp

**Deliverables:** Fully multi-tenant app with user registration, per-user data isolation, and backward-compatible data migration.

---

## Stage 6.12: Whale Activity Tracking
**Goal:** Detect and display institutional ("whale") buying/selling activity for stocks in a user's portfolio, giving retail investors early signals about large-player moves.

### What Counts as Whale Activity

Whale activity is detected by combining three data dimensions — SEC filings (the most authoritative source), options flow, and volume anomalies:

**SEC Filings (EDGAR — institutional & insider transactions):**
1. **Form 4 (Insider Transactions)** — Officers, directors, and 10%+ owners must file within 2 business days of a buy/sell. Shows exact shares, price, and whether it's a direct purchase (most bullish) or option exercise. Insider *buying* with personal money is a strong bullish signal; cluster buying (multiple insiders in a short window) is even stronger.
2. **Form 13F (Institutional Holdings)** — Hedge funds and institutions with $100M+ AUM file quarterly. By diffing consecutive 13F filings we detect position increases (accumulation) and decreases (distribution) by major funds.
3. **Schedule 13D/13G (5%+ Ownership Stakes)** — Filed when an entity crosses the 5% ownership threshold. A new 13D (activist intent) is a major whale event. 13D amendments showing increased positions are also significant.

**Options Flow & Volume Anomalies:**
4. **Unusual Options Volume** — Single-day options volume exceeding 3× the 20-day average, weighted toward large-premium trades
5. **Large Block Trades** — Individual equity trades of 10,000+ shares (or $500K+), sourced from volume spike analysis against intraday patterns
6. **Put/Call OI Shifts** — Significant day-over-day changes in open interest ratios (>0.3 swing), indicating new large directional positions
7. **Dark Pool Activity Proxy** — Off-exchange volume percentage anomalies (volume spikes not reflected in price movement suggest dark pool accumulation/distribution)
8. **Volume-Price Divergence** — High volume with minimal price change suggests large players accumulating without moving the market

Each signal is classified as **bullish** (whale buying), **bearish** (whale selling), or **neutral**.

### Data Source Strategy

Two free, public APIs — no paid subscriptions needed:

**SEC EDGAR API (filings):**
- **Full-text search**: `https://efts.sec.gov/LATEST/search-index?q=<TICKER>&forms=4,13F-HR,SC 13D` — find recent filings by form type and ticker
- **Company filings**: `https://data.sec.gov/submissions/CIK<cik>.json` — all filings for a CIK (Central Index Key)
- **XBRL data**: `https://data.sec.gov/api/xbrl/companyfacts/CIK<cik>.json` — structured ownership data
- **Form 4 XML**: parsed for transaction type (P=purchase, S=sale), shares, price, ownership percentage
- **13F CSV**: quarterly holdings table with CUSIP, shares, value — diffed against prior quarter
- **Rate limit**: 10 requests/second with `User-Agent` header required (SEC fair access policy)
- **Ticker→CIK mapping**: `https://www.sec.gov/files/company_tickers.json` — cached locally

**yfinance (options & volume):**
- **`ticker.options`** — options chain with volume, OI, strike, expiry (detects unusual options activity)
- **`ticker.history(period='5d', interval='1h')`** — intraday volume patterns (detects block trade signatures)
- **`ticker.info['averageVolume']`** / **`ticker.info['volume']`** — volume ratio for spike detection
- Historical options OI is tracked locally by storing daily snapshots (new model)

### Current State

- `OptionsSnapshot` model already tracks `put_call_volume_ratio`, `put_call_oi_ratio`, `has_unusual_activity`, and `unusual_activity_details` per ticker
- `OptionsDataService.fetch_options_data()` already fetches and scores options data during `refresh_ticker()`
- Holdings table already shows opportunity score badges per ticker — whale indicator will sit beside it
- The `refresh_ticker()` pipeline is the natural hook for computing whale signals

### Tasks

#### 6.12a: Models
- [ ] **Create `SECFiling` model** in `analysis/models.py`:
  - `ticker` — FK to Ticker
  - `form_type` — CharField (e.g., `4`, `13F-HR`, `SC 13D`, `SC 13G`)
  - `filed_at` — DateTimeField (SEC filing date)
  - `filer_name` — CharField (insider name or institution name)
  - `filer_title` — CharField (nullable — "CEO", "CFO", "Director", etc. for Form 4)
  - `transaction_type` — CharField choices: `buy`, `sell`, `exercise`, `acquisition`, `disposition`
  - `shares` — DecimalField (number of shares transacted)
  - `price_per_share` — DecimalField (nullable — not always available on 13F)
  - `total_value` — DecimalField (shares × price, or reported value)
  - `ownership_pct` — DecimalField (nullable — percentage of outstanding shares, for 13D/G)
  - `accession_number` — CharField (unique SEC filing ID, for dedup and linking back to EDGAR)
  - `raw_data` — JSONField (full parsed filing data for reference)
  - `created_at` — DateTimeField(auto_now_add=True)
  - `unique_together = ('ticker', 'accession_number')`
- [ ] **Create `WhaleActivity` model** in `analysis/models.py`:
  - `ticker` — FK to Ticker (not OneToOne — we store a rolling history of daily snapshots)
  - `date` — DateField (one record per ticker per day)
  - `signal` — CharField choices: `bullish`, `bearish`, `neutral`
  - `confidence` — IntegerField (0-100, how strong the whale signal is)
  - **SEC filing signals:**
  - `insider_buy_count` — IntegerField (Form 4 purchases in last 30 days)
  - `insider_sell_count` — IntegerField (Form 4 sales in last 30 days)
  - `insider_net_value` — DecimalField (net dollar value: buys minus sells)
  - `institutional_change_pct` — DecimalField (nullable — quarter-over-quarter 13F position change %)
  - `has_13d_filing` — BooleanField (new or amended 13D/G in last 90 days)
  - **Options/volume signals:**
  - `options_volume_ratio` — DecimalField (today's options vol / 20-day avg)
  - `oi_change_ratio` — DecimalField (day-over-day OI shift magnitude)
  - `block_trade_detected` — BooleanField
  - `volume_price_divergence` — DecimalField (volume spike vs price change ratio)
  - **Combined:**
  - `details` — JSONField (full breakdown of all signal components for tooltip/detail view)
  - `computed_at` — DateTimeField(auto_now=True)
  - `unique_together = ('ticker', 'date')`
- [ ] **Create `CIKMapping` model** in `analysis/models.py` (cache for SEC ticker→CIK lookups):
  - `ticker` — OneToOneField to Ticker
  - `cik` — CharField (SEC Central Index Key, zero-padded 10 digits)
  - `updated_at` — DateTimeField(auto_now=True)
- [ ] **Add migration**
- [ ] **Register all three models in admin**

#### 6.12b: SECFilingService
- [ ] **Create `SECFilingService`** in `analysis/services.py` (or new `analysis/sec_service.py`):
  - `_resolve_cik(ticker)` — look up CIK from `CIKMapping` cache; if miss, fetch from `https://www.sec.gov/files/company_tickers.json`, cache result; set `User-Agent` header per SEC policy
  - `fetch_form4_filings(ticker, days=90)` — query EDGAR full-text search for recent Form 4 filings; parse XML for transaction details (transaction code: P=purchase, S=sale, A=grant, M=exercise); store as `SECFiling` records; skip duplicates via `accession_number`
  - `fetch_13f_changes(ticker)` — query EDGAR for the two most recent 13F-HR filings containing this ticker's CUSIP; compute quarter-over-quarter share count change and percentage; return as institutional accumulation/distribution signal
  - `fetch_13d_filings(ticker, days=90)` — query EDGAR for recent SC 13D and SC 13D/A filings; flag new activist positions or increased stakes
  - `refresh_sec_data(ticker)` — orchestrates all three fetch methods for a ticker; respects SEC 10 req/sec rate limit with a shared throttle (`time.sleep(0.1)` between requests)
- [ ] **SEC rate limiting** — use a module-level timestamp to ensure no more than 10 requests/second across all calls
- [ ] **Error handling** — SEC EDGAR can return 403 (rate limited) or 500; retry once after 2s, then log and skip gracefully

#### 6.12c: WhaleDetectionService
- [ ] **Create `WhaleDetectionService`** in `analysis/services.py` with the following methods:
  - `detect_whale_activity(ticker)` — main entry point, returns WhaleActivity instance; orchestrates SEC + options + volume analysis
  - **SEC analysis methods:**
  - `_analyze_insider_activity(ticker)` — query `SECFiling` for Form 4 records in last 30 days; count buys vs sells; compute net dollar value; flag cluster buying (3+ insiders buying within 2 weeks) as high-confidence bullish; weight direct purchases higher than option exercises
  - `_analyze_institutional_holdings(ticker)` — use `SECFiling` 13F data to compute quarter-over-quarter position changes; flag if top-5 holders increased by >10% (bullish) or decreased by >10% (bearish)
  - `_analyze_activist_positions(ticker)` — check for 13D/G filings in `SECFiling`; any new 13D = high-confidence bullish event; amended 13D with increased stake = moderate bullish
  - **Options/volume methods (unchanged):**
  - `_analyze_options_flow(ticker)` — compare today's options volume to 20-day average, flag if >3× with large premiums; check put/call OI shift vs yesterday's snapshot
  - `_analyze_volume_anomalies(ticker)` — fetch 5-day intraday data, detect block-trade-sized volume spikes (single-bar volume >5× the bar average); compute volume-price divergence (high volume + <0.5% price change = accumulation signal)
  - **Scoring:**
  - `_compute_whale_signal(sec_signals, options_signals, volume_signals)` — weighted combination: SEC filings 50% (most authoritative), options flow 30%, volume anomalies 20%; SEC sub-weights: insider buys 25%, institutional changes 15%, activist 13D 10%; produces overall bullish/bearish/neutral with confidence (0-100)
  - `_store_daily_snapshot(ticker, signal_data)` — create or update `WhaleActivity` for today's date
- [ ] **Historical OI tracking** — each call to `_analyze_options_flow` stores current OI in `WhaleActivity.details` so tomorrow's run can compute the delta

#### 6.12d: Integrate into Refresh Pipeline
- [ ] **Hook `SECFilingService.refresh_sec_data(ticker)` into `StockDataService.refresh_ticker()`** — fetch latest SEC filings after options data; SEC data changes infrequently so skip if last fetch was <6 hours ago (check `CIKMapping.updated_at` or `SECFiling.created_at`)
- [ ] **Hook `WhaleDetectionService.detect_whale_activity(ticker)` into `refresh_ticker()`** — runs after SEC + options + indicators are computed; combines all signals into today's `WhaleActivity` snapshot
- [ ] **Add to `refresh_all`** — whale detection runs for each ticker in the batch; SEC calls are rate-limited (0.1s between) so add to the existing sleep budget

#### 6.12e: Portfolio Holdings Display
- [ ] **Add whale indicator column to holdings table** (`portfolio/partials/holdings_table.html`):
  - New column after the opportunity score column
  - Show a whale emoji + directional arrow: 🐋↑ (bullish), 🐋↓ (bearish), or nothing if neutral/no data
  - Color-coded: green for bullish, red for bearish
  - Confidence shown as small text (e.g., "78%")
  - Tooltip on hover showing quick summary (e.g., "3 insider buys + unusual options volume")
- [ ] **Pass whale data to template** — update `get_holdings()` or `portfolio_detail` view to annotate each holding with its latest `WhaleActivity` record
- [ ] **Add whale column to portfolio list cards** — show count of tickers with active whale signals (e.g., "2 whale alerts")

#### 6.12f: Whale Detail Expandable Row
- [ ] **Expandable whale detail** — clicking the whale indicator expands a sub-row (like lot details) showing:
  - **SEC Insider Activity** section:
    - Recent Form 4 transactions table (date, insider name, title, buy/sell, shares, price, total value)
    - Net insider sentiment bar (green for net buying, red for net selling)
    - "Cluster buy" badge if 3+ insiders bought within 2 weeks
  - **Institutional Holdings** section:
    - Quarter-over-quarter position change (e.g., "+12.5% institutional accumulation")
    - Top filer names if available from 13F data
  - **Activist Alert** section (only if 13D filed):
    - Filer name, ownership percentage, filing date
    - Badge: "New Activist Position" or "Increased Stake"
  - **Options Flow** section:
    - Options volume ratio (e.g., "4.2× normal")
    - OI shift direction and magnitude
  - **Volume Anomalies** section:
    - Block trade detection (yes/no with estimated size)
    - Volume-price divergence metric
  - Timestamp of last detection
- [ ] **Style** — use existing collapsible row pattern from holdings table; dark theme consistent; sections use accordion or tabs to keep it compact

#### 6.12g: Tests
- [ ] **Model tests** — SECFiling creation and unique_together on accession_number; WhaleActivity creation and unique_together on (ticker, date); CIKMapping OneToOne constraint; signal choices validation
- [ ] **SECFilingService tests** (mock HTTP responses):
  - CIK resolution and caching (hit vs miss)
  - Form 4 XML parsing — extracts transaction type, shares, price correctly
  - 13F quarterly diff — detects accumulation and distribution
  - 13D detection — flags new activist positions
  - Rate limiting respected (no more than 10 req/sec)
  - Graceful handling of SEC 403/500 errors
  - Duplicate filing skipped via accession_number
- [ ] **WhaleDetectionService tests** (mock SEC + yfinance data):
  - Insider cluster buying (3+ Form 4 purchases in 2 weeks) → high-confidence bullish
  - Single large insider sale → moderate bearish
  - Institutional accumulation >10% → bullish signal
  - New 13D filing → high-confidence bullish event
  - High options volume → bullish signal detected
  - Large OI shift toward puts → bearish signal
  - Volume spike with no price movement → accumulation (bullish)
  - Normal activity across all dimensions → neutral
  - Combined scoring weights SEC signals highest
  - Confidence scoring accuracy
- [ ] **View tests** — whale indicator renders in holdings table, expandable detail shows SEC insider table, handles missing whale data gracefully
- [ ] **Integration test** — `refresh_ticker` triggers SEC fetch + whale detection and stores results

**Deliverables:** Whale activity detection combining SEC EDGAR filings (Form 4 insider transactions, 13F institutional holdings, 13D activist stakes) with yfinance options/volume data, displayed as a compact indicator beside each stock in the portfolio holdings table with expandable details showing insider trades, institutional moves, and options flow.

---

## Stage 7: Polish, Performance & Deployment
**Goal:** Final UI polish, performance optimization, and deployment readiness.

### Tasks
- [ ] Dark mode toggle (Bootstrap dark theme)
- [ ] Dashboard homepage with portfolio summary widgets:
  - Total portfolio value with daily change
  - Top gainers / losers
  - Top opportunities
  - Recent news highlights
- [ ] Loading states and skeleton screens (HTMX indicators)
- [ ] Error pages (404, 500) with consistent styling
- [ ] Performance optimization:
  - Database query optimization (select_related, prefetch_related)
  - Template fragment caching
  - Lazy loading for charts
- [ ] Comprehensive test suite (models, views, services)
- [ ] `manage.py` commands for data refresh, cleanup
- [ ] Docker support (Dockerfile + docker-compose.yml)
- [ ] Production settings (environment variables, allowed hosts)
- [ ] Update README with setup instructions

**Deliverables:** Production-ready, polished application.

---

## Stage Dependencies

```
Stage 1 ──► Stage 2 ──► Stage 3 ──► Stage 4 ──┐
                                                ├──► Stage 6 ──► Stage 7
                                    Stage 5 ────┘
```

Stages 4 and 5 can be developed in parallel after Stage 3.
Stage 6 requires both 4 and 5.
Stage 7 runs last as final polish.

---

## Estimated Scope per Stage

| Stage | Key Focus                  | Models | Views | Templates |
|-------|----------------------------|--------|-------|-----------|
| 1     | Foundation & Models        | 3      | 0     | 1 (base)  |
| 2     | Portfolio CRUD UI          | 0      | ~8    | ~6        |
| 3     | Market Data & Charts       | 1      | ~4    | ~3        |
| 4     | Technical Indicators       | 1      | ~2    | ~2        |
| 5     | News & AI Sentiment        | 1      | ~2    | ~2        |
| 6     | Opportunity Dashboard      | 1      | ~4    | ~4        |
| 7     | Polish & Deployment        | 0      | ~2    | ~3        |
