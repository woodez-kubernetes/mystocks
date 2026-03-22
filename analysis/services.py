import hashlib
import logging
from decimal import Decimal

import ollama
import pandas as pd
from django.conf import settings as django_settings
from ta.momentum import RSIIndicator
from ta.trend import MACD, SMAIndicator
from ta.volatility import BollingerBands

from analysis.models import AIAnalysis, IndicatorSnapshot, OptionsSnapshot, PortfolioAnalysis
from market.models import PriceHistory

logger = logging.getLogger(__name__)

MIN_DATA_POINTS = 50


def _to_dec(val, places=2):
    if val is None or pd.isna(val):
        return None
    return round(Decimal(str(val)), places)


class TechnicalIndicatorService:

    @staticmethod
    def compute_indicators(ticker):
        """Compute all technical indicators for a ticker and save an IndicatorSnapshot."""
        qs = PriceHistory.objects.filter(ticker=ticker).order_by('date')
        if qs.count() < MIN_DATA_POINTS:
            logger.info(f"{ticker.symbol}: not enough data ({qs.count()} < {MIN_DATA_POINTS})")
            return None

        df = pd.DataFrame(
            list(qs.values('date', 'open', 'high', 'low', 'close', 'volume'))
        )
        for col in ('open', 'high', 'low', 'close'):
            df[col] = df[col].astype(float)
        df['volume'] = df['volume'].astype(float)
        df.set_index('date', inplace=True)

        close = df['close']
        last_close = close.iloc[-1]

        # --- RSI (14) ---
        rsi_ind = RSIIndicator(close=close, window=14)
        rsi_val = rsi_ind.rsi().iloc[-1]
        rsi_signal = TechnicalIndicatorService._rsi_signal(rsi_val)

        # --- MACD (12, 26, 9) ---
        macd_ind = MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
        macd_val = macd_ind.macd().iloc[-1]
        macd_signal_line = macd_ind.macd_signal().iloc[-1]
        macd_hist = macd_ind.macd_diff().iloc[-1]
        macd_signal = TechnicalIndicatorService._macd_signal(macd_hist, macd_val, macd_signal_line)

        # --- Bollinger Bands (20, 2) ---
        bb_ind = BollingerBands(close=close, window=20, window_dev=2)
        bb_upper = bb_ind.bollinger_hband().iloc[-1]
        bb_middle = bb_ind.bollinger_mavg().iloc[-1]
        bb_lower = bb_ind.bollinger_lband().iloc[-1]
        bb_signal = TechnicalIndicatorService._bb_signal(last_close, bb_lower, bb_upper, bb_middle)

        # --- SMA 50 / 200 ---
        sma_50_series = SMAIndicator(close=close, window=50).sma_indicator()
        sma_50_val = sma_50_series.iloc[-1] if len(close) >= 50 else None
        sma_200_val = None
        if len(close) >= 200:
            sma_200_val = SMAIndicator(close=close, window=200).sma_indicator().iloc[-1]
        sma_signal = TechnicalIndicatorService._sma_signal(last_close, sma_50_val, sma_200_val)

        # --- Volume ratio (current vs 20-day avg) ---
        vol = df['volume']
        vol_avg_20 = vol.rolling(20).mean().iloc[-1]
        vol_current = vol.iloc[-1]
        volume_ratio = vol_current / vol_avg_20 if vol_avg_20 and vol_avg_20 > 0 else None
        volume_signal = TechnicalIndicatorService._volume_signal(volume_ratio)

        # --- Sentiment (from NewsArticle aggregate) ---
        from market.services import NewsService
        avg_sentiment = NewsService.get_aggregate_sentiment(ticker)
        sentiment_val = float(avg_sentiment) if avg_sentiment is not None else None
        sentiment_signal = TechnicalIndicatorService._sentiment_signal(sentiment_val)

        # --- Options Score (from OptionsSnapshot if available) ---
        options_score_val = None
        try:
            opts = ticker.options_snapshot
            if opts and opts.options_score is not None:
                options_score_val = opts.options_score
        except OptionsSnapshot.DoesNotExist:
            pass

        # --- Opportunity Score ---
        score = TechnicalIndicatorService._compute_score(
            rsi_val, macd_hist, last_close, bb_lower, bb_upper, bb_middle,
            sma_50_val, sma_200_val, volume_ratio, sentiment_val,
            options_score_val
        )

        # --- Price Target Range ---
        max_pain = None
        try:
            opts = ticker.options_snapshot
            if opts and opts.max_pain is not None:
                max_pain = float(opts.max_pain)
        except OptionsSnapshot.DoesNotExist:
            pass

        buy_target, sell_target = TechnicalIndicatorService._compute_price_targets(
            last_close, bb_lower, bb_upper, sma_50_val, sma_200_val,
            ticker.week_52_high, ticker.week_52_low, max_pain
        )

        snapshot, _ = IndicatorSnapshot.objects.update_or_create(
            ticker=ticker,
            defaults={
                'rsi': _to_dec(rsi_val),
                'rsi_signal': rsi_signal,
                'macd': _to_dec(macd_val, 4),
                'macd_signal_line': _to_dec(macd_signal_line, 4),
                'macd_histogram': _to_dec(macd_hist, 4),
                'macd_signal': macd_signal,
                'bb_upper': _to_dec(bb_upper),
                'bb_middle': _to_dec(bb_middle),
                'bb_lower': _to_dec(bb_lower),
                'bb_signal': bb_signal,
                'sma_50': _to_dec(sma_50_val),
                'sma_200': _to_dec(sma_200_val),
                'sma_signal': sma_signal,
                'volume_ratio': _to_dec(volume_ratio),
                'volume_signal': volume_signal,
                'sentiment_score': _to_dec(sentiment_val, 3) if sentiment_val is not None else None,
                'sentiment_signal': sentiment_signal,
                'opportunity_score': score,
                'buy_target': _to_dec(buy_target),
                'sell_target': _to_dec(sell_target),
            }
        )
        return snapshot

    # ---------- Signal helpers ----------

    @staticmethod
    def _rsi_signal(rsi):
        if pd.isna(rsi):
            return 'hold'
        if rsi < 30:
            return 'buy'
        if rsi > 70:
            return 'sell'
        return 'hold'

    @staticmethod
    def _macd_signal(histogram, macd_val, signal_line):
        if pd.isna(histogram) or pd.isna(macd_val):
            return 'hold'
        # Bullish crossover: histogram turning positive
        if histogram > 0 and macd_val > signal_line:
            return 'buy'
        if histogram < 0 and macd_val < signal_line:
            return 'sell'
        return 'hold'

    @staticmethod
    def _bb_signal(price, lower, upper, middle):
        if any(pd.isna(v) for v in (price, lower, upper, middle)):
            return 'hold'
        bb_range = upper - lower
        if bb_range == 0:
            return 'hold'
        # Price near lower band → buy, near upper band → sell
        position = (price - lower) / bb_range
        if position < 0.15:
            return 'buy'
        if position > 0.85:
            return 'sell'
        return 'hold'

    @staticmethod
    def _sma_signal(price, sma_50, sma_200):
        if sma_50 is None or pd.isna(sma_50):
            return 'hold'
        if sma_200 is not None and not pd.isna(sma_200):
            # Golden cross / death cross
            if sma_50 > sma_200 and price > sma_50:
                return 'buy'
            if sma_50 < sma_200 and price < sma_50:
                return 'sell'
        else:
            # Only SMA 50 available
            if price > sma_50:
                return 'buy'
            elif price < sma_50:
                return 'sell'
        return 'hold'

    @staticmethod
    def _volume_signal(ratio):
        if ratio is None or pd.isna(ratio):
            return 'hold'
        if ratio > 1.5:
            return 'buy'  # High volume = notable activity
        if ratio < 0.5:
            return 'sell'  # Low volume = weak conviction
        return 'hold'

    @staticmethod
    def _sentiment_signal(sentiment):
        if sentiment is None:
            return 'hold'
        if sentiment >= 0.15:
            return 'buy'
        if sentiment <= -0.15:
            return 'sell'
        return 'hold'

    # ---------- Price Targets ----------

    @staticmethod
    def _compute_price_targets(price, bb_lower, bb_upper, sma_50, sma_200,
                               week_52_high, week_52_low, max_pain=None):
        """Compute buy and sell price target ranges from available data.

        Buy target (support zone): averaged from lower indicators.
        Sell target (resistance zone): averaged from upper indicators.
        Returns (buy_target, sell_target) as floats, or (None, None).
        """
        if price is None or pd.isna(price):
            return None, None

        price = float(price)
        buy_components = []
        sell_components = []

        # Bollinger Bands
        if bb_lower is not None and not pd.isna(bb_lower):
            buy_components.append(float(bb_lower))
        if bb_upper is not None and not pd.isna(bb_upper):
            sell_components.append(float(bb_upper))

        # SMA 200 as support, SMA 50 as resistance reference
        if sma_200 is not None and not pd.isna(sma_200):
            buy_components.append(float(sma_200))
        if sma_50 is not None and not pd.isna(sma_50):
            if float(sma_50) > price:
                sell_components.append(float(sma_50))
            else:
                buy_components.append(float(sma_50))

        # Options max pain as price gravity
        if max_pain is not None:
            if max_pain < price:
                buy_components.append(max_pain)
            else:
                sell_components.append(max_pain)

        # 52-week range (weighted toward current price: 70% range extreme, 30% current)
        if week_52_low is not None:
            adjusted_low = float(week_52_low) * 0.7 + price * 0.3
            buy_components.append(adjusted_low)
        if week_52_high is not None:
            adjusted_high = float(week_52_high) * 0.7 + price * 0.3
            sell_components.append(adjusted_high)

        buy_target = round(sum(buy_components) / len(buy_components), 2) if buy_components else None
        sell_target = round(sum(sell_components) / len(sell_components), 2) if sell_components else None

        # Sanity: buy target should be below current price, sell above
        if buy_target is not None and buy_target >= price:
            buy_target = round(price * 0.95, 2)
        if sell_target is not None and sell_target <= price:
            sell_target = round(price * 1.05, 2)

        return buy_target, sell_target

    # ---------- Composite Score ----------

    @staticmethod
    def _compute_score(rsi, macd_hist, price, bb_lower, bb_upper, bb_middle,
                       sma_50, sma_200, volume_ratio, sentiment=None,
                       options_score=None):
        """Weighted average of sub-scores.

        With all data:    RSI(12%), MACD(12%), BB(12%), SMA(22%), Vol(10%), Sentiment(17%), Options(15%)
        Without options:  RSI(15%), MACD(15%), BB(15%), SMA(25%), Vol(10%), Sentiment(20%)
        Without sentiment: RSI(20%), MACD(20%), BB(20%), SMA(25%), Vol(15%)
        """
        scores = {}

        # RSI sub-score: 0-100, lower RSI = higher score (buying opportunity)
        if not pd.isna(rsi):
            scores['rsi'] = max(0, min(100, 100 - rsi))
        else:
            scores['rsi'] = 50

        # MACD sub-score: positive histogram = bullish
        if not pd.isna(macd_hist):
            if price and price > 0:
                norm = (macd_hist / price) * 1000
                scores['macd'] = max(0, min(100, 50 + norm * 10))
            else:
                scores['macd'] = 50
        else:
            scores['macd'] = 50

        # BB sub-score: position within bands (lower = better buy)
        if not any(pd.isna(v) for v in (price, bb_lower, bb_upper)):
            bb_range = bb_upper - bb_lower
            if bb_range > 0:
                position = (price - bb_lower) / bb_range
                scores['bb'] = max(0, min(100, (1 - position) * 100))
            else:
                scores['bb'] = 50
        else:
            scores['bb'] = 50

        # SMA sub-score
        if sma_50 is not None and not pd.isna(sma_50):
            sma_score = 50
            if price > sma_50:
                sma_score += 15
            else:
                sma_score -= 15
            if sma_200 is not None and not pd.isna(sma_200):
                if sma_50 > sma_200:
                    sma_score += 20
                else:
                    sma_score -= 20
            scores['sma'] = max(0, min(100, sma_score))
        else:
            scores['sma'] = 50

        # Volume sub-score
        if volume_ratio is not None and not pd.isna(volume_ratio):
            scores['volume'] = max(0, min(100, volume_ratio * 40 + 20))
        else:
            scores['volume'] = 50

        # Sentiment sub-score: map -1..+1 to 0..100
        has_sentiment = sentiment is not None
        if has_sentiment:
            scores['sentiment'] = max(0, min(100, (sentiment + 1) * 50))

        # Options sub-score (already 0-100 from OptionsDataService)
        has_options = options_score is not None

        # Weighted average — adjust weights based on data availability
        if has_sentiment and has_options:
            weighted = (
                scores['rsi'] * 0.12
                + scores['macd'] * 0.12
                + scores['bb'] * 0.12
                + scores['sma'] * 0.22
                + scores['volume'] * 0.10
                + scores['sentiment'] * 0.17
                + options_score * 0.15
            )
        elif has_sentiment:
            weighted = (
                scores['rsi'] * 0.15
                + scores['macd'] * 0.15
                + scores['bb'] * 0.15
                + scores['sma'] * 0.25
                + scores['volume'] * 0.10
                + scores['sentiment'] * 0.20
            )
        elif has_options:
            weighted = (
                scores['rsi'] * 0.18
                + scores['macd'] * 0.18
                + scores['bb'] * 0.18
                + scores['sma'] * 0.22
                + scores['volume'] * 0.12
                + options_score * 0.12
            )
        else:
            weighted = (
                scores['rsi'] * 0.20
                + scores['macd'] * 0.20
                + scores['bb'] * 0.20
                + scores['sma'] * 0.25
                + scores['volume'] * 0.15
            )
        return int(round(max(0, min(100, weighted))))


class AIAnalysisService:

    @staticmethod
    def _build_prompt(ticker, indicators, news_articles):
        """Build the LLM prompt from ticker data, indicators, and news."""
        lines = [
            f"Analyze {ticker.symbol} ({ticker.company_name}) stock briefly in 2-4 sentences.",
            "",
            "Current data:",
            f"- Price: ${ticker.last_price}, Day change: {ticker.day_change_pct}%",
            f"- Sector: {ticker.sector or 'Unknown'}",
        ]

        if ticker.pe_ratio:
            lines.append(f"- P/E Ratio: {ticker.pe_ratio}")
        if ticker.market_cap:
            cap_b = float(ticker.market_cap) / 1_000_000_000
            lines.append(f"- Market Cap: ${cap_b:.1f}B")
        if ticker.week_52_high and ticker.week_52_low:
            lines.append(f"- 52-Week Range: ${ticker.week_52_low} - ${ticker.week_52_high}")

        if indicators:
            lines.extend([
                "",
                "Technical indicators:",
                f"- RSI(14): {indicators.rsi} ({indicators.rsi_signal})",
                f"- MACD histogram: {indicators.macd_histogram} ({indicators.macd_signal})",
                f"- Bollinger Band signal: {indicators.bb_signal}",
                f"- SMA trend: {indicators.sma_signal} (SMA50=${indicators.sma_50}, SMA200=${indicators.sma_200})",
                f"- Volume ratio: {indicators.volume_ratio}x ({indicators.volume_signal})",
                f"- Opportunity score: {indicators.opportunity_score}/100",
            ])
            if indicators.sentiment_score is not None:
                lines.append(f"- News sentiment: {indicators.sentiment_score} ({indicators.sentiment_signal})")
            if indicators.buy_target and indicators.sell_target:
                lines.extend([
                    "",
                    "Price target range:",
                    f"- Buy target (support): ${indicators.buy_target}",
                    f"- Sell target (resistance): ${indicators.sell_target}",
                    f"- Current price vs targets: {'near support' if ticker.last_price and float(ticker.last_price) <= float(indicators.buy_target) * 1.05 else 'near resistance' if ticker.last_price and float(ticker.last_price) >= float(indicators.sell_target) * 0.95 else 'mid-range'}",
                ])

        # Options data
        try:
            opts = ticker.options_snapshot
            if opts:
                lines.extend([
                    "",
                    "Options sentiment (contrarian):",
                    f"- Put/Call volume ratio: {opts.put_call_volume_ratio}",
                    f"- Put/Call OI ratio: {opts.put_call_oi_ratio}",
                    f"- IV skew: {opts.iv_skew}",
                    f"- Max pain: ${opts.max_pain}",
                    f"- Options score: {opts.options_score}/100 ({opts.options_signal})",
                ])
                if opts.has_unusual_activity:
                    lines.append(f"- Unusual options activity detected")
        except Exception:
            pass

        if news_articles:
            lines.extend(["", "Recent headlines:"])
            for article in news_articles[:5]:
                sentiment = f" [{article.sentiment_label}]" if article.sentiment_label else ""
                lines.append(f"- {article.title[:100]}{sentiment}")

        lines.extend([
            "",
            "Provide a concise 2-4 sentence analysis covering the technical outlook, "
            "options positioning, price target levels, and key factors. "
            "Reference specific support/resistance levels when available. "
            "Do not give financial advice. Do not use bullet points.",
        ])
        return "\n".join(lines)

    @staticmethod
    def _compute_prompt_hash(prompt_text):
        return hashlib.sha256(prompt_text.encode()).hexdigest()[:16]

    @staticmethod
    def generate_analysis(ticker, force=False):
        """Generate AI analysis for a ticker. Returns AIAnalysis instance or None."""
        # Gather inputs
        try:
            indicators = ticker.indicators
        except Exception:
            indicators = None

        from market.models import NewsArticle
        news_articles = list(NewsArticle.objects.filter(ticker=ticker).order_by('-published_at')[:5])

        prompt_text = AIAnalysisService._build_prompt(ticker, indicators, news_articles)
        prompt_hash = AIAnalysisService._compute_prompt_hash(prompt_text)

        # Skip if unchanged
        if not force:
            try:
                existing = AIAnalysis.objects.get(ticker=ticker)
                if existing.prompt_hash == prompt_hash:
                    logger.info(f"{ticker.symbol}: AI analysis unchanged, skipping")
                    return existing
            except AIAnalysis.DoesNotExist:
                pass

        # Call Ollama
        try:
            host = getattr(django_settings, 'OLLAMA_HOST', 'http://localhost:11434')
            model = getattr(django_settings, 'OLLAMA_MODEL', 'llama3.2:1b')
            timeout = getattr(django_settings, 'OLLAMA_TIMEOUT', 60)

            client = ollama.Client(host=host, timeout=timeout)
            response = client.chat(
                model=model,
                messages=[
                    {
                        'role': 'system',
                        'content': (
                            'You are a concise stock market analyst. Provide brief, '
                            'factual analysis based on the data provided. Never give '
                            'buy/sell recommendations or financial advice.'
                        ),
                    },
                    {
                        'role': 'user',
                        'content': prompt_text,
                    },
                ],
            )
            analysis_text = response['message']['content'].strip()
        except Exception as e:
            logger.error(f"Ollama error for {ticker.symbol}: {e}")
            return None

        analysis_obj, _ = AIAnalysis.objects.update_or_create(
            ticker=ticker,
            defaults={
                'analysis_text': analysis_text,
                'model_name': getattr(django_settings, 'OLLAMA_MODEL', 'llama3.2:1b'),
                'prompt_hash': prompt_hash,
            },
        )
        logger.info(f"{ticker.symbol}: AI analysis generated ({len(analysis_text)} chars)")
        return analysis_obj


class PortfolioAnalysisService:

    @staticmethod
    def _gather_candidates(portfolio):
        """Gather all tickers from portfolio holdings and watchlist with their data."""
        from portfolio.models import Ticker, WatchlistItem
        from market.models import NewsArticle

        # Portfolio tickers
        portfolio_symbols = set(
            portfolio.lots.values_list('ticker__symbol', flat=True).distinct()
        )

        # Watchlist tickers
        watchlist_symbols = set(
            WatchlistItem.objects.values_list('ticker__symbol', flat=True)
        )

        all_symbols = portfolio_symbols | watchlist_symbols
        tickers = Ticker.objects.filter(symbol__in=all_symbols)

        candidates = []
        for ticker in tickers:
            try:
                indicators = ticker.indicators
            except IndicatorSnapshot.DoesNotExist:
                indicators = None

            try:
                opts = ticker.options_snapshot
            except OptionsSnapshot.DoesNotExist:
                opts = None

            news = list(NewsArticle.objects.filter(ticker=ticker).order_by('-published_at')[:3])

            candidates.append({
                'ticker': ticker,
                'indicators': indicators,
                'options': opts,
                'news': news,
                'in_portfolio': ticker.symbol in portfolio_symbols,
                'in_watchlist': ticker.symbol in watchlist_symbols,
            })
        return candidates

    @staticmethod
    def _pick_top_2(candidates):
        """Select the top 2 stocks by opportunity score."""
        scored = [
            c for c in candidates
            if c['indicators'] and c['indicators'].opportunity_score is not None
        ]
        scored.sort(key=lambda c: c['indicators'].opportunity_score, reverse=True)
        return scored[:2]

    @staticmethod
    def _build_ticker_summary(c):
        """Build a text summary for a single candidate ticker."""
        t = c['ticker']
        ind = c['indicators']
        opts = c['options']

        lines = [f"{t.symbol} ({t.company_name or 'N/A'}) - ${t.last_price}"]
        lines.append(f"  Sector: {t.sector or 'Unknown'}")

        if t.day_change_pct is not None:
            lines.append(f"  Day change: {'+' if t.day_change_pct >= 0 else ''}{t.day_change_pct}%")
        if t.pe_ratio:
            lines.append(f"  P/E: {t.pe_ratio}")
        if t.market_cap:
            cap_b = float(t.market_cap) / 1_000_000_000
            lines.append(f"  Market cap: ${cap_b:.1f}B")
        if t.week_52_high and t.week_52_low:
            lines.append(f"  52-week range: ${t.week_52_low} - ${t.week_52_high}")

        if ind:
            lines.append(f"  Opportunity score: {ind.opportunity_score}/100")
            lines.append(f"  RSI: {ind.rsi} ({ind.rsi_signal}), MACD: {ind.macd_signal}, BB: {ind.bb_signal}")
            lines.append(f"  SMA: {ind.sma_signal} (50=${ind.sma_50}, 200=${ind.sma_200})")
            lines.append(f"  Volume: {ind.volume_ratio}x ({ind.volume_signal})")
            if ind.sentiment_score is not None:
                lines.append(f"  Sentiment: {ind.sentiment_score} ({ind.sentiment_signal})")
            if ind.buy_target and ind.sell_target:
                lines.append(f"  Price targets: Buy=${ind.buy_target}, Sell=${ind.sell_target}")

        if opts:
            lines.append(f"  Options: P/C vol={opts.put_call_volume_ratio}, OI={opts.put_call_oi_ratio}, "
                         f"IV skew={opts.iv_skew}, Max pain=${opts.max_pain}, "
                         f"Score={opts.options_score}/100 ({opts.options_signal})")
            if opts.has_unusual_activity:
                lines.append(f"  ** Unusual options activity detected")

        source = []
        if c['in_portfolio']:
            source.append("in portfolio")
        if c['in_watchlist']:
            source.append("on watchlist")
        lines.append(f"  Source: {', '.join(source)}")

        if c['news']:
            lines.append("  Recent headlines:")
            for article in c['news']:
                sentiment = f" [{article.sentiment_label}]" if article.sentiment_label else ""
                lines.append(f"    - {article.title[:80]}{sentiment}")

        return "\n".join(lines)

    @staticmethod
    def _build_top_picks_prompt(top_picks, portfolio):
        """Build prompt for top 2 stock picks analysis."""
        lines = [
            f"You are analyzing the '{portfolio.name}' portfolio. From all stocks in this portfolio "
            f"and watchlist, these 2 stocks have the highest opportunity scores and are the best "
            f"candidates to increase position size.",
            "",
            "For each stock, provide a detailed investment case (3-5 sentences) explaining:",
            "- Why the technical indicators support adding to this position",
            "- What the options market sentiment tells us (contrarian view)",
            "- Key support/resistance levels from the price targets",
            "- Any catalysts or risks from recent news",
            "- A specific entry strategy (e.g., accumulate near support at $X)",
            "",
        ]

        for i, c in enumerate(top_picks, 1):
            lines.append(f"--- PICK #{i} ---")
            lines.append(PortfolioAnalysisService._build_ticker_summary(c))
            lines.append("")

        lines.extend([
            "Format your response as:",
            "PICK 1: [SYMBOL]",
            "[detailed case]",
            "",
            "PICK 2: [SYMBOL]",
            "[detailed case]",
            "",
            "Be specific with numbers and price levels. Do not give financial advice. "
            "State observations and data-driven reasoning only.",
        ])
        return "\n".join(lines)

    @staticmethod
    def _build_portfolio_analysis_prompt(candidates, portfolio, holdings):
        """Build prompt for overall portfolio analysis."""
        lines = [
            f"Analyze the '{portfolio.name}' portfolio as a whole. Provide a comprehensive "
            f"4-6 sentence analysis covering portfolio composition, diversification, "
            f"overall technical health, and outlook.",
            "",
            "Portfolio summary:",
            f"- Total cost: ${portfolio.total_cost}",
        ]
        if portfolio.total_value:
            lines.append(f"- Market value: ${portfolio.total_value}")
        if portfolio.total_gain_loss is not None:
            lines.append(f"- Total gain/loss: ${portfolio.total_gain_loss} ({portfolio.total_gain_loss_pct:.1f}%)")

        # Sector breakdown
        sectors = {}
        for c in candidates:
            if c['in_portfolio']:
                sector = c['ticker'].sector or 'Unknown'
                sectors[sector] = sectors.get(sector, 0) + 1
        if sectors:
            lines.append(f"- Sectors: {', '.join(f'{s} ({n})' for s, n in sorted(sectors.items()))}")

        # Avg opportunity score
        scored = [c for c in candidates if c['in_portfolio'] and c['indicators']]
        if scored:
            avg_score = sum(c['indicators'].opportunity_score for c in scored) / len(scored)
            buy_count = sum(1 for c in scored if c['indicators'].opportunity_score >= 70)
            sell_count = sum(1 for c in scored if c['indicators'].opportunity_score < 40)
            lines.append(f"- Avg opportunity score: {avg_score:.0f}/100 ({buy_count} buy signals, {sell_count} sell signals)")

        lines.extend(["", "Holdings:"])
        for c in candidates:
            if c['in_portfolio']:
                lines.append(PortfolioAnalysisService._build_ticker_summary(c))
                lines.append("")

        # Watchlist context
        watchlist_candidates = [c for c in candidates if c['in_watchlist'] and not c['in_portfolio']]
        if watchlist_candidates:
            lines.extend(["Watchlist (not yet in portfolio):"])
            for c in watchlist_candidates:
                lines.append(PortfolioAnalysisService._build_ticker_summary(c))
                lines.append("")

        lines.extend([
            "Provide a 4-6 sentence portfolio analysis covering:",
            "- Overall portfolio health and performance",
            "- Sector concentration or diversification gaps",
            "- Which holdings are strongest/weakest based on technicals and options",
            "- Key risks to watch (earnings, macro, sector-specific)",
            "- Any rebalancing considerations",
            "",
            "Be specific. Reference actual ticker symbols, scores, and price levels. "
            "Do not give financial advice. State observations only.",
        ])
        return "\n".join(lines)

    @staticmethod
    def generate_analysis(portfolio, force=False):
        """Generate top picks and portfolio analysis. Returns PortfolioAnalysis or None."""
        holdings = portfolio.get_holdings()
        candidates = PortfolioAnalysisService._gather_candidates(portfolio)
        top_picks = PortfolioAnalysisService._pick_top_2(candidates)

        if not candidates:
            logger.info(f"Portfolio '{portfolio.name}': no candidates for analysis")
            return None

        # Build prompts
        picks_prompt = ""
        if top_picks:
            picks_prompt = PortfolioAnalysisService._build_top_picks_prompt(top_picks, portfolio)
        portfolio_prompt = PortfolioAnalysisService._build_portfolio_analysis_prompt(
            candidates, portfolio, holdings
        )

        combined_hash = hashlib.sha256(
            (picks_prompt + portfolio_prompt).encode()
        ).hexdigest()[:16]

        # Skip if unchanged
        if not force:
            try:
                existing = PortfolioAnalysis.objects.get(portfolio=portfolio)
                if existing.prompt_hash == combined_hash:
                    logger.info(f"Portfolio '{portfolio.name}': analysis unchanged, skipping")
                    return existing
            except PortfolioAnalysis.DoesNotExist:
                pass

        host = getattr(django_settings, 'OLLAMA_HOST', 'http://localhost:11434')
        model = getattr(django_settings, 'OLLAMA_MODEL', 'llama3.2:1b')
        timeout = getattr(django_settings, 'OLLAMA_TIMEOUT', 60)

        system_msg = (
            'You are a concise portfolio analyst. Provide factual, data-driven analysis '
            'based on the technical indicators, options data, news, and metrics provided. '
            'Never give buy/sell recommendations or financial advice.'
        )

        # Generate top picks analysis
        top_picks_text = ""
        top_pick_symbols = []
        if picks_prompt:
            try:
                client = ollama.Client(host=host, timeout=timeout)
                response = client.chat(
                    model=model,
                    messages=[
                        {'role': 'system', 'content': system_msg},
                        {'role': 'user', 'content': picks_prompt},
                    ],
                )
                top_picks_text = response['message']['content'].strip()
                top_pick_symbols = [c['ticker'].symbol for c in top_picks]
            except Exception as e:
                logger.error(f"Ollama error for portfolio picks: {e}")

        # Generate portfolio analysis
        portfolio_analysis_text = ""
        try:
            client = ollama.Client(host=host, timeout=timeout)
            response = client.chat(
                model=model,
                messages=[
                    {'role': 'system', 'content': system_msg},
                    {'role': 'user', 'content': portfolio_prompt},
                ],
            )
            portfolio_analysis_text = response['message']['content'].strip()
        except Exception as e:
            logger.error(f"Ollama error for portfolio analysis: {e}")

        if not top_picks_text and not portfolio_analysis_text:
            return None

        analysis_obj, _ = PortfolioAnalysis.objects.update_or_create(
            portfolio=portfolio,
            defaults={
                'top_picks_text': top_picks_text,
                'top_pick_symbols': top_pick_symbols,
                'portfolio_analysis_text': portfolio_analysis_text,
                'model_name': model,
                'prompt_hash': combined_hash,
            },
        )
        logger.info(f"Portfolio '{portfolio.name}': analysis generated")
        return analysis_obj
