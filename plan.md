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
