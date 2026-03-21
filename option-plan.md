# Options Data as Price Direction Indicator — Implementation Plan

## Overview

Add options chain data from Yahoo Finance (`yfinance`) as a new indicator to help predict stock price direction. Options data reflects market participants' expectations and positioning, providing a forward-looking signal that complements the existing technical and sentiment indicators.

## Decisions (Confirmed)

1. **Metrics:** All 5 — P/C volume ratio, P/C OI ratio, IV skew, max pain, unusual activity
2. **Composite weight:** Options = 15%
3. **Expirations:** Nearest expirations within 30 days
4. **UI:** Options Sentiment card on ticker detail page + radar chart update on opportunities page
5. **Storage:** Cache in DB via `OptionsSnapshot` model (same pattern as `IndicatorSnapshot`)
6. **Interpretation:** Contrarian — high put/call ratio (excessive fear) = buying opportunity, not bearish signal

---

## Phase 1: Data Fetching — Options Service

**File:** `market/services.py` (new class `OptionsDataService`)

Pull options chain data via `yfinance` (`Ticker.options` for expiry dates, `Ticker.option_chain(date)` for calls/puts DataFrames).

### Metrics to Compute

| Metric | Source | Signal Logic |
|--------|--------|-------------|
| **Put/Call Volume Ratio** | Sum of put volume / sum of call volume across near-term expirations | **Contrarian:** > 1.0 = excessive fear = Bullish (buying opportunity), < 0.7 = complacency = Bearish |
| **Put/Call Open Interest Ratio** | Sum of put OI / sum of call OI | **Contrarian:** > 1.0 = heavy put positioning = Bullish, < 0.7 = Bearish |
| **Implied Volatility Skew** | Avg IV of OTM puts vs avg IV of OTM calls | **Contrarian:** Put IV >> Call IV = extreme hedging = Bullish (fear overdone) |
| **Max Pain** | Strike where total dollar value of expired options is maximized | Price tends to gravitate toward max pain near expiry |
| **Unusual Activity Flag** | Any single option contract with volume > 5x open interest | Signals large directional bets |

### Implementation Details

```python
class OptionsDataService:
    @staticmethod
    def fetch_options_data(symbol: str) -> dict:
        """Fetch and compute options metrics for a ticker."""
        # 1. Get available expiration dates
        # 2. Select nearest 2-4 expirations (within ~30 days)
        # 3. For each expiration, pull calls + puts DataFrames
        # 4. Compute: put/call volume ratio, OI ratio, IV skew, max pain
        # 5. Detect unusual activity
        # 6. Return structured dict of all metrics

    @staticmethod
    def compute_max_pain(calls_df, puts_df) -> float:
        """Calculate max pain strike price."""

    @staticmethod
    def compute_iv_skew(calls_df, puts_df, current_price) -> float:
        """Calculate IV skew between OTM puts and OTM calls."""

    @staticmethod
    def detect_unusual_activity(calls_df, puts_df) -> list:
        """Flag contracts where volume > 5x open interest."""
```

### Error Handling

- Some tickers have no options (e.g., ETFs, foreign stocks) — return `None` gracefully
- Weekend/holiday stale data — use last available
- Missing IV values in some contracts — skip those contracts in IV skew calc

---

## Phase 2: Data Model — Store Options Snapshot

**File:** `analysis/models.py`

### New Model: `OptionsSnapshot`

```python
class OptionsSnapshot(models.Model):
    ticker = models.OneToOneField(Ticker, on_delete=models.CASCADE, related_name='options_snapshot')
    put_call_volume_ratio = models.DecimalField(max_digits=6, decimal_places=3, null=True)
    put_call_oi_ratio = models.DecimalField(max_digits=6, decimal_places=3, null=True)
    iv_skew = models.DecimalField(max_digits=6, decimal_places=3, null=True)
    max_pain = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    has_unusual_activity = models.BooleanField(default=False)
    unusual_activity_details = models.JSONField(default=list, blank=True)
    expirations_analyzed = models.JSONField(default=list)  # which expiry dates were used
    options_signal = models.CharField(max_length=10, choices=[('buy','Buy'),('hold','Hold'),('sell','Sell')], default='hold')
    options_score = models.IntegerField(default=50)  # 0-100 normalized score
    updated_at = models.DateTimeField(auto_now=True)
```

### Migration

- Standard Django `makemigrations` + `migrate`
- OneToOne to Ticker — same pattern as `IndicatorSnapshot`

---

## Phase 3: Integrate into Composite Opportunity Score

**File:** `analysis/services.py` — `TechnicalIndicatorService`

### Options Sub-Score Calculation (0–100)

```
options_score = weighted_average(
    put_call_volume_score,   # 40% — most responsive to current sentiment
    put_call_oi_score,       # 35% — reflects accumulated positioning
    iv_skew_score,           # 25% — reflects fear/greed asymmetry
)
```

Scoring logic (contrarian — fear = buying opportunity):
- **P/C Volume Ratio**: 2.0 → score 90 (extreme fear = strong buy), 1.0 → score 50 (neutral), 0.3 → score 10 (complacency = bearish)
- **P/C OI Ratio**: Same contrarian scale as volume ratio
- **IV Skew**: Put IV >> Call IV = high score (fear overdone, buy signal); Call IV >> Put IV = low score (complacency)

### Revised Composite Score Weights

| Indicator | Current Weight (w/ sentiment) | Proposed New Weight |
|-----------|-------------------------------|---------------------|
| RSI | 15% | 12% |
| MACD | 15% | 12% |
| Bollinger Bands | 15% | 12% |
| SMA 50/200 | 25% | 22% |
| Volume | 10% | 10% |
| Sentiment | 20% | 17% |
| **Options** | — | **15%** |

When options data is unavailable (no options for ticker), fall back to current weights.

---

## Phase 4: Hook into Refresh Pipeline

**File:** `market/services.py` — `StockDataService.refresh_ticker()`

Add options data fetch to the existing refresh chain:

```
quote → company info → price history → news → indicators → OPTIONS DATA
```

- Call `OptionsDataService.fetch_options_data(symbol)` after indicators
- Save/update `OptionsSnapshot` model
- Pass options score to `TechnicalIndicatorService.compute_indicators()` for composite score

### Management Command Update

**File:** `market/management/commands/refresh_prices.py`

- Options fetch happens automatically as part of `refresh_ticker()` — no separate command needed
- Add `--skip-options` flag for faster refreshes when options data isn't needed

---

## Phase 5: UI — Ticker Detail Page

**File:** `market/templates/market/ticker_detail.html`

### New "Options Sentiment" Card

- **Put/Call Ratio Gauge** — visual indicator (green/yellow/red)
- **Max Pain vs Current Price** — shows expected price gravity
- **Unusual Activity Alerts** — highlighted if detected
- **Options Signal** — Buy/Hold/Sell badge (same style as existing indicators)
- **Options Score** — 0-100 displayed alongside other indicator scores

### Opportunities Page Update

**File:** `analysis/templates/analysis/opportunities.html`

- Add options score to the radar chart (7th axis)
- Show options signal in the opportunities table

---

## Phase 6: Tests

**Files:** `market/tests.py`, `analysis/tests.py`

### Test Cases

1. **OptionsDataService unit tests**
   - Mock yfinance option_chain responses
   - Test P/C ratio calculation with known data
   - Test max pain calculation
   - Test IV skew calculation
   - Test unusual activity detection
   - Test ticker with no options available (graceful handling)

2. **OptionsSnapshot model tests**
   - Create/update snapshot
   - OneToOne constraint

3. **Composite score integration tests**
   - Score with options data present
   - Score with options data absent (fallback weights)

4. **Refresh pipeline tests**
   - Options data fetched during refresh_ticker()
   - Error in options fetch doesn't break rest of pipeline

---

## Implementation Order

1. **Phase 1** — `OptionsDataService` class with all metric calculations
2. **Phase 2** — `OptionsSnapshot` model + migration
3. **Phase 3** — Integrate options score into composite scoring
4. **Phase 4** — Hook into refresh pipeline
5. **Phase 5** — UI updates (ticker detail + opportunities)
6. **Phase 6** — Tests

## Dependencies

- No new packages needed — `yfinance` already provides options chain data
- No API key changes — uses same Yahoo Finance endpoints
- `ta` library not needed for options calculations (pure math)

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Yahoo Finance rate limiting on options calls | Respect existing 1s delay; options = 1 extra API call per expiry date |
| Low-volume tickers with sparse options data | Minimum volume/OI threshold before computing metrics |
| Options data only available during market hours | Cache last known values; flag staleness in UI |
| Some tickers have no options at all | Graceful fallback — exclude from composite, use current weights |
