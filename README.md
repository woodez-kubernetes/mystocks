# MyStocks - Stock Portfolio Analysis & Opportunity Finder

A Django-based stock portfolio tracker that helps you identify buying opportunities using technical indicators, news sentiment analysis, and AI-powered scoring.

## Features

- **Portfolio Management** — Track multiple portfolios with individual lots (different buy dates and prices)
- **Live Market Data** — Real-time prices and historical charts via yfinance
- **Technical Analysis** — RSI, MACD, Bollinger Bands, moving averages, volume analysis
- **AI Sentiment** — News headline sentiment scoring to gauge market mood
- **Opportunity Scoring** — Composite 0-100 score combining technicals + sentiment
- **Watchlist & Alerts** — Monitor tickers and get notified of buying opportunities

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Browser (User)                              │
│                  Bootstrap 5 + HTMX + Chart.js                      │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ HTTP / HTMX partials
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Django Application                            │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │  portfolio    │  │   market     │  │  analysis    │              │
│  │  app          │  │   app        │  │  app         │              │
│  │              │  │              │  │              │              │
│  │ • Portfolio   │  │ • StockData  │  │ • Technical  │              │
│  │ • Ticker      │  │   Service    │  │   Indicator  │              │
│  │ • Lot         │  │ • PriceCache │  │   Service    │              │
│  │ • CRUD Views  │  │ • Charts API │  │ • News       │              │
│  │              │  │              │  │   Service    │              │
│  │              │  │              │  │ • Sentiment  │              │
│  │              │  │              │  │   Analyzer   │              │
│  │              │  │              │  │ • Scoring    │              │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘              │
│         │                 │                 │                       │
│         └────────────┬────┴────────────┬────┘                      │
│                      ▼                 ▼                            │
│              ┌──────────────┐  ┌──────────────┐                    │
│              │   SQLite     │  │  django-q2   │                    │
│              │   Database   │  │  (scheduler) │                    │
│              └──────────────┘  └──────────────┘                    │
└─────────────────────────────────────────────────────────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ yfinance │ │ News RSS │ │ OpenAI   │
        │ API      │ │ Feeds    │ │ API      │
        └──────────┘ └──────────┘ └──────────┘
```

---

## Data Model

```
┌──────────────────────┐
│      Portfolio        │
├──────────────────────┤
│ id (PK)              │
│ name                 │
│ created_at           │
│ notes                │
└──────────┬───────────┘
           │ 1
           │
           │ *
┌──────────┴───────────┐       ┌──────────────────────┐
│        Lot            │       │      Ticker           │
├──────────────────────┤       ├──────────────────────┤
│ id (PK)              │  *  1 │ id (PK)              │
│ portfolio_id (FK) ───┤───────│ symbol (unique)      │
│ ticker_id (FK) ──────┤       │ company_name         │
│ shares               │       │ sector               │
│ cost_basis           │       │ last_price            │
│ purchase_date        │       │ last_updated          │
│ notes                │       └──────────┬───────────┘
└──────────────────────┘                  │ 1
                                          │
                          ┌───────────────┼───────────────┐
                          │ *             │ *             │ *
              ┌───────────┴──┐ ┌─────────┴────┐ ┌───────┴──────────┐
              │ PriceHistory  │ │ Indicator    │ │ NewsArticle      │
              ├──────────────┤ │ Snapshot     │ ├──────────────────┤
              │ ticker_id FK │ ├──────────────┤ │ ticker_id FK     │
              │ date         │ │ ticker_id FK │ │ title            │
              │ open         │ │ date         │ │ url              │
              │ high         │ │ rsi          │ │ source           │
              │ low          │ │ macd         │ │ published_date   │
              │ close        │ │ macd_signal  │ │ sentiment_score  │
              │ volume       │ │ bb_upper     │ │ fetched_at       │
              └──────────────┘ │ bb_lower     │ └──────────────────┘
                               │ sma_50       │
                               │ sma_200      │
                               │ volume_ratio │
                               │ opp_score    │
                               └──────────────┘
```

---

## UI Layout

### Dashboard (Homepage)
```
┌─────────────────────────────────────────────────────────────────┐
│  MyStocks                                    [🔔 Alerts] [⚙]  │
├──────────┬──────────────────────────────────────────────────────┤
│          │                                                      │
│ 📊 Dash  │  Portfolio Value          Daily Change               │
│          │  ┌─────────────────┐      ┌─────────────────┐       │
│ 📁 Port  │  │   $125,430.50   │      │    +$1,245.30   │       │
│          │  │   ▲ 2.3% total  │      │    +1.0% today  │       │
│ 🔍 Opps  │  └─────────────────┘      └─────────────────┘       │
│          │                                                      │
│ 👁 Watch │  Top Opportunities         Top Movers                │
│          │  ┌─────────────────┐      ┌─────────────────┐       │
│ 📰 News  │  │ 1. AAPL  [85]  │      │ ▲ NVDA  +3.2%  │       │
│          │  │ 2. MSFT  [78]  │      │ ▲ AAPL  +1.8%  │       │
│ ⚙ Sett  │  │ 3. GOOGL [72]  │      │ ▼ TSLA  -0.5%  │       │
│          │  └─────────────────┘      └─────────────────┘       │
│          │                                                      │
│          │  Recent News Headlines                               │
│          │  ┌───────────────────────────────────────────┐       │
│          │  │ 🟢 AAPL: Apple reports record Q4 earnings │       │
│          │  │ 🟡 MSFT: Microsoft cloud growth slows     │       │
│          │  │ 🔴 TSLA: Tesla faces new regulatory...    │       │
│          │  └───────────────────────────────────────────┘       │
└──────────┴──────────────────────────────────────────────────────┘
```

### Portfolio Detail View
```
┌─────────────────────────────────────────────────────────────────┐
│  Portfolio: Tech Growth          Total: $85,200  ▲ +12.4%      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Ticker   Shares  Avg Cost   Current   Gain/Loss    Score      │
│  ─────────────────────────────────────────────────────────      │
│  ▼ AAPL    150    $142.30    $178.50   +$5,430 ▲   [85] 🟢    │
│    ├─ Lot 1: 100 shares @ $135.00  (2024-01-15)                │
│    ├─ Lot 2:  30 shares @ $155.00  (2024-06-20)                │
│    └─ Lot 3:  20 shares @ $162.50  (2024-09-10)                │
│                                                                 │
│  ► MSFT     50    $380.00    $420.00   +$2,000 ▲   [78] 🟢    │
│  ► GOOGL    25    $140.00    $165.00   +$625   ▲   [72] 🟡    │
│                                                                 │
│  [+ Add Ticker]                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Ticker Analysis View
```
┌─────────────────────────────────────────────────────────────────┐
│  AAPL - Apple Inc.          $178.50  ▲ +1.8%    Score: [85]    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Price Chart                          [1D] [1W] [1M] [3M] [1Y]│
│  ┌───────────────────────────────────────────────────┐         │
│  │            ╱╲                                      │         │
│  │     ╱╲   ╱  ╲    ╱╲  ╱╲                           │         │
│  │   ╱   ╲╱    ╲  ╱  ╲╱  ╲   ╱                      │         │
│  │  ╱            ╲╱        ╲ ╱                        │         │
│  │╱                          ╲    ── Price            │         │
│  │  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─    ── SMA 50           │         │
│  │  · · · · · · · · · · · · ·    ── SMA 200          │         │
│  └───────────────────────────────────────────────────┘         │
│                                                                 │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐              │
│  │  RSI: 32    │ │ MACD: Bull  │ │ BB: Lower   │              │
│  │  ████░░░░░░ │ │  Crossover  │ │  Near band  │              │
│  │  Oversold 🟢│ │  Bullish 🟢 │ │  Bullish 🟢 │              │
│  └─────────────┘ └─────────────┘ └─────────────┘              │
│                                                                 │
│  Key Stats                      Sentiment                      │
│  ┌─────────────────────┐       ┌─────────────────────┐        │
│  │ P/E:     28.5       │       │ 7-Day Avg: +0.65    │        │
│  │ Mkt Cap: $2.8T      │       │ ██████████░░ 🟢     │        │
│  │ 52W Hi:  $199.62    │       │                     │        │
│  │ 52W Lo:  $124.17    │       │ Recent Headlines:   │        │
│  │ Div:     0.55%      │       │ 🟢 Record earnings  │        │
│  │ Vol:     58.2M      │       │ 🟡 New product...   │        │
│  └─────────────────────┘       └─────────────────────┘        │
│                                                                 │
│  [+ Add Lot to Portfolio]                                      │
└─────────────────────────────────────────────────────────────────┘
```

### Opportunity Score Breakdown
```
┌─────────────────────────────────────────────────────────────────┐
│  Opportunity Score: 85 / 100                                    │
│                                                                 │
│              Technical (70%)          Sentiment (30%)           │
│                                                                 │
│          RSI ████████░░  35/100       News  ████████░░ 75/100  │
│         MACD █████████░  82/100                                │
│           BB ████████░░  78/100                                │
│       SMA 50 ███████░░░  65/100                                │
│      SMA 200 ████████░░  80/100                                │
│       Volume ██████░░░░  55/100                                │
│                                                                 │
│  ┌─────────────────────────────────────────────────────┐       │
│  │                  Radar Chart                        │       │
│  │              RSI                                    │       │
│  │            ╱    ╲                                   │       │
│  │     Vol  ╱   ●    ╲  MACD                          │       │
│  │         │  ╱    ╲  │                                │       │
│  │         │╱        ╲│                                │       │
│  │   SMA200 ●────────● BB                             │       │
│  │           ╲      ╱                                  │       │
│  │            ╲  ● ╱                                   │       │
│  │             SMA50                                   │       │
│  └─────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

### Price Update Flow
```
┌──────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────┐
│ Scheduler│────►│ StockData    │────►│   yfinance   │────►│ Price    │
│ (q2)     │     │ Service      │     │   API        │     │ History  │
│ every 15m│     │              │     │              │     │ (SQLite) │
└──────────┘     └──────────────┘     └──────────────┘     └──────────┘
                                                                │
                                                                ▼
                                                          ┌──────────┐
                                                          │ Indicator│
                                                          │ Service  │
                                                          │ (compute)│
                                                          └────┬─────┘
                                                               │
                                                               ▼
                                                          ┌──────────┐
                                                          │ Indicator│
                                                          │ Snapshot │
                                                          │ (SQLite) │
                                                          └──────────┘
```

### Opportunity Scoring Flow
```
┌──────────────┐     ┌──────────────┐
│  Technical   │     │  Sentiment   │
│  Indicators  │     │  Score       │
│              │     │              │
│  RSI:    35  │     │  News: +0.65 │
│  MACD:   82  │     │              │
│  BB:     78  │     │  Weight: 30% │
│  SMA50:  65  │     │              │
│  SMA200: 80  │     └──────┬───────┘
│  Volume: 55  │            │
│              │            │
│  Weight: 70% │            │
└──────┬───────┘            │
       │                    │
       ▼                    ▼
┌─────────────────────────────────┐
│    Weighted Score Calculator     │
│                                 │
│  Tech:  (35+82+78+65+80+55)/6  │
│         × 0.70 = 46.1          │
│                                 │
│  Sent:  75 × 0.30 = 22.5       │
│                                 │
│  Total: 46.1 + 22.5 = 69       │
│  Normalized: 85 / 100          │
└─────────────────────────────────┘
```

---

## Project Structure

```
mystocks/
├── mystocks_project/           # Django project settings
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── portfolio/                  # Portfolio management app
│   ├── models.py               # Portfolio, Ticker, Lot
│   ├── views.py                # CRUD views
│   ├── forms.py                # Django forms
│   ├── urls.py
│   └── templates/portfolio/
│       ├── dashboard.html
│       ├── portfolio_list.html
│       ├── portfolio_detail.html
│       └── partials/           # HTMX partial templates
├── market/                     # Market data app
│   ├── services.py             # StockDataService
│   ├── models.py               # PriceHistory
│   ├── views.py                # Chart data API
│   └── templates/market/
│       └── ticker_detail.html
├── analysis/                   # Analysis & scoring app
│   ├── services.py             # TechnicalIndicatorService
│   ├── sentiment.py            # AI sentiment analyzer
│   ├── scoring.py              # Opportunity score calculator
│   ├── models.py               # IndicatorSnapshot, NewsArticle
│   ├── views.py                # Opportunity dashboard
│   └── templates/analysis/
│       ├── opportunities.html
│       └── comparison.html
├── templates/                  # Global templates
│   └── base.html               # Base layout with nav
├── static/                     # Static assets
│   ├── css/
│   ├── js/
│   └── img/
├── requirements.txt
├── manage.py
├── plan.md
├── progress.md
└── README.md
```

---

## Tech Stack Details

| Component        | Technology                | Purpose                          |
|------------------|---------------------------|----------------------------------|
| Backend          | Django 5.x                | Web framework                    |
| Frontend         | Bootstrap 5 + HTMX        | Responsive UI, no-reload updates |
| Charts           | Chart.js                  | Interactive price/indicator charts|
| Database         | SQLite                    | Data storage                     |
| Stock Data       | yfinance                  | Prices, fundamentals, news       |
| Technical Lib    | `ta` (Python)             | RSI, MACD, Bollinger, etc.       |
| AI Sentiment     | OpenAI API / VADER        | News headline scoring            |
| Task Scheduler   | django-q2                 | Background data refresh          |
| Data Processing  | pandas                    | Data manipulation                |

---

## Setup & Running

```bash
# Clone
git clone <repo-url>
cd mystocks

# Virtual environment
python -m venv venv
source venv/bin/activate

# Dependencies
pip install -r requirements.txt

# Database
python manage.py migrate

# Run
python manage.py runserver
```

Visit `http://localhost:8000` in your browser.

### Environment Variables (optional)

| Variable           | Description                    | Default          |
|--------------------|--------------------------------|------------------|
| `OPENAI_API_KEY`   | OpenAI API key for sentiment   | None (uses VADER)|
| `SECRET_KEY`       | Django secret key              | Auto-generated   |
| `DEBUG`            | Debug mode                     | True             |

---

## License

MIT
