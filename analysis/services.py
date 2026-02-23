import hashlib
import logging
from decimal import Decimal

import ollama
import pandas as pd
from django.conf import settings as django_settings
from ta.momentum import RSIIndicator
from ta.trend import MACD, SMAIndicator
from ta.volatility import BollingerBands

from analysis.models import AIAnalysis, IndicatorSnapshot
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

        # --- Opportunity Score ---
        score = TechnicalIndicatorService._compute_score(
            rsi_val, macd_hist, last_close, bb_lower, bb_upper, bb_middle,
            sma_50_val, sma_200_val, volume_ratio, sentiment_val
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

    # ---------- Composite Score ----------

    @staticmethod
    def _compute_score(rsi, macd_hist, price, bb_lower, bb_upper, bb_middle,
                       sma_50, sma_200, volume_ratio, sentiment=None):
        """Weighted average of sub-scores.

        With sentiment: RSI(15%), MACD(15%), BB(15%), SMA(25%), Vol(10%), Sentiment(20%)
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

        # Weighted average — adjust weights based on sentiment availability
        if has_sentiment:
            weighted = (
                scores['rsi'] * 0.15
                + scores['macd'] * 0.15
                + scores['bb'] * 0.15
                + scores['sma'] * 0.25
                + scores['volume'] * 0.10
                + scores['sentiment'] * 0.20
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

        if news_articles:
            lines.extend(["", "Recent headlines:"])
            for article in news_articles[:5]:
                sentiment = f" [{article.sentiment_label}]" if article.sentiment_label else ""
                lines.append(f"- {article.title[:100]}{sentiment}")

        lines.extend([
            "",
            "Provide a concise 2-4 sentence analysis covering the technical outlook "
            "and key factors. Do not give financial advice. Do not use bullet points.",
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
