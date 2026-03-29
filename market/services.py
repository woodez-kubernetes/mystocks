import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone as dt_tz
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime

import requests
import yfinance as yf
from django.db.models import Avg
from django.utils import timezone
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from market.models import NewsArticle, PriceHistory, RSSFeedSource
from portfolio.models import Ticker

logger = logging.getLogger(__name__)

VALID_PERIODS = ['5d', '1mo', '3mo', '6mo', '1y', '2y', '5y']


def _nested_get(d, *keys):
    """Safely get a nested dict value, e.g. _nested_get(d, 'a', 'b') -> d['a']['b']."""
    for key in keys:
        if isinstance(d, dict):
            d = d.get(key)
        else:
            return None
    return d


def _to_decimal(value, places=2):
    """Safely convert a value to Decimal, returning None on failure."""
    if value is None:
        return None
    try:
        import math
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        result = round(Decimal(str(value)), places)
        if result.is_nan() or result.is_infinite():
            return None
        return result
    except (InvalidOperation, ValueError, TypeError):
        return None


class StockDataService:

    @staticmethod
    def get_quote(symbol):
        """Fetch current quote data for a symbol."""
        try:
            stock = yf.Ticker(symbol)
            info = stock.info
            if not info or info.get('regularMarketPrice') is None:
                fast = stock.fast_info
                return {
                    'price': _to_decimal(getattr(fast, 'last_price', None)),
                    'prev_close': _to_decimal(getattr(fast, 'previous_close', None)),
                    'day_change': None,
                    'day_change_pct': None,
                    'volume': getattr(fast, 'last_volume', None),
                }

            price = _to_decimal(info.get('regularMarketPrice') or info.get('currentPrice'))
            prev_close = _to_decimal(info.get('regularMarketPreviousClose') or info.get('previousClose'))
            day_change = None
            day_change_pct = None
            if price and prev_close and prev_close != 0:
                day_change = price - prev_close
                day_change_pct = (day_change / prev_close) * Decimal('100')

            return {
                'price': price,
                'prev_close': prev_close,
                'day_change': day_change,
                'day_change_pct': _to_decimal(day_change_pct),
                'volume': info.get('regularMarketVolume') or info.get('volume'),
            }
        except Exception:
            logger.exception(f"Failed to fetch quote for {symbol}")
            return None

    @staticmethod
    def get_history(symbol, period='1y'):
        """Fetch historical OHLCV data as a list of dicts."""
        if period not in VALID_PERIODS:
            period = '1y'
        try:
            stock = yf.Ticker(symbol)
            df = stock.history(period=period)
            if df.empty:
                return []

            records = []
            for idx, row in df.iterrows():
                records.append({
                    'date': idx.date() if hasattr(idx, 'date') else idx,
                    'open': _to_decimal(row.get('Open')),
                    'high': _to_decimal(row.get('High')),
                    'low': _to_decimal(row.get('Low')),
                    'close': _to_decimal(row.get('Close')),
                    'volume': int(row.get('Volume', 0)),
                })
            return records
        except Exception:
            logger.exception(f"Failed to fetch history for {symbol}")
            return []

    @staticmethod
    def get_company_info(symbol):
        """Fetch company fundamentals."""
        try:
            stock = yf.Ticker(symbol)
            info = stock.info
            if not info:
                return {}
            return {
                'company_name': info.get('shortName') or info.get('longName', ''),
                'sector': info.get('sector', ''),
                'market_cap': info.get('marketCap'),
                'pe_ratio': _to_decimal(info.get('trailingPE')),
                'dividend_yield': _to_decimal(info.get('dividendYield'), places=4),
                'week_52_high': _to_decimal(info.get('fiftyTwoWeekHigh')),
                'week_52_low': _to_decimal(info.get('fiftyTwoWeekLow')),
                'avg_volume': info.get('averageVolume'),
            }
        except Exception:
            logger.exception(f"Failed to fetch company info for {symbol}")
            return {}

    @staticmethod
    def refresh_ticker(ticker_obj):
        """Full refresh: update Ticker fields + cache PriceHistory."""
        symbol = ticker_obj.symbol

        # 1. Quote data
        quote = StockDataService.get_quote(symbol)
        if quote:
            ticker_obj.last_price = quote['price']
            ticker_obj.prev_close = quote['prev_close']
            ticker_obj.day_change = quote['day_change']
            ticker_obj.day_change_pct = quote['day_change_pct']

        # 2. Company info
        info = StockDataService.get_company_info(symbol)
        if info:
            if info.get('company_name'):
                ticker_obj.company_name = info['company_name']
            if info.get('sector'):
                ticker_obj.sector = info['sector']
            ticker_obj.market_cap = info.get('market_cap')
            ticker_obj.pe_ratio = info.get('pe_ratio')
            ticker_obj.dividend_yield = info.get('dividend_yield')
            ticker_obj.week_52_high = info.get('week_52_high')
            ticker_obj.week_52_low = info.get('week_52_low')
            ticker_obj.avg_volume = info.get('avg_volume')

        ticker_obj.last_updated = timezone.now()
        ticker_obj.save()

        # 3. Cache price history (1 year)
        history = StockDataService.get_history(symbol, period='1y')
        if history:
            # Bulk upsert: delete existing, insert fresh
            existing_dates = set(
                PriceHistory.objects.filter(ticker=ticker_obj)
                .values_list('date', flat=True)
            )
            new_records = []
            for rec in history:
                if rec['date'] not in existing_dates and rec['close'] is not None:
                    new_records.append(PriceHistory(
                        ticker=ticker_obj,
                        date=rec['date'],
                        open=rec['open'] or Decimal('0'),
                        high=rec['high'] or Decimal('0'),
                        low=rec['low'] or Decimal('0'),
                        close=rec['close'],
                        volume=rec['volume'],
                    ))
            if new_records:
                PriceHistory.objects.bulk_create(new_records, ignore_conflicts=True)

        # 4. Fetch news + sentiment
        try:
            NewsService.refresh_news(ticker_obj)
        except Exception:
            logger.exception(f"Failed to fetch news for {symbol}")

        # 5. Fetch options data
        try:
            options_data = OptionsDataService.fetch_options_data(symbol)
            if options_data:
                from analysis.models import OptionsSnapshot
                OptionsSnapshot.objects.update_or_create(
                    ticker=ticker_obj,
                    defaults={
                        'put_call_volume_ratio': _to_decimal(options_data['put_call_volume_ratio'], 3),
                        'put_call_oi_ratio': _to_decimal(options_data['put_call_oi_ratio'], 3),
                        'iv_skew': _to_decimal(options_data['iv_skew'], 4),
                        'max_pain': _to_decimal(options_data['max_pain']),
                        'has_unusual_activity': options_data['has_unusual_activity'],
                        'unusual_activity_details': options_data['unusual_activity_details'],
                        'expirations_analyzed': options_data['expirations_analyzed'],
                        'options_score': options_data['options_score'],
                        'options_signal': options_data['options_signal'],
                    }
                )
        except Exception:
            logger.exception(f"Failed to fetch options data for {symbol}")

        # 6. Compute technical indicators (includes sentiment + options in score)
        try:
            from analysis.services import TechnicalIndicatorService
            TechnicalIndicatorService.compute_indicators(ticker_obj)
        except Exception:
            logger.exception(f"Failed to compute indicators for {symbol}")

        # 7. Fetch SEC filing data (rate-limited, skip if recent)
        try:
            from analysis.sec_service import SECFilingService
            SECFilingService.refresh_sec_data(ticker_obj)
        except Exception:
            logger.exception(f"Failed to fetch SEC data for {symbol}")

        # 8. Detect whale activity (combines SEC + options + volume signals)
        try:
            from analysis.services import WhaleDetectionService
            WhaleDetectionService.detect_whale_activity(ticker_obj)
        except Exception:
            logger.exception(f"Failed to detect whale activity for {symbol}")

        return ticker_obj

    @staticmethod
    def refresh_all(sleep_between=1.0):
        """Refresh all tickers that are in at least one portfolio or on a watchlist."""
        from django.db.models import Q
        tickers = Ticker.objects.filter(
            Q(lots__isnull=False) | Q(watchlist_entries__isnull=False)
        ).distinct()
        results = []
        for ticker in tickers:
            try:
                StockDataService.refresh_ticker(ticker)
                results.append((ticker.symbol, True))
            except Exception:
                logger.exception(f"Failed to refresh {ticker.symbol}")
                results.append((ticker.symbol, False))
            time.sleep(sleep_between)

        # Fetch RSS feeds after ticker refresh
        try:
            RSSNewsService.fetch_all_feeds()
        except Exception:
            logger.exception("Failed to fetch RSS feeds")

        return results


class NewsService:
    _analyzer = None

    @classmethod
    def _get_analyzer(cls):
        if cls._analyzer is None:
            cls._analyzer = SentimentIntensityAnalyzer()
        return cls._analyzer

    @staticmethod
    def fetch_news(ticker_obj):
        """Fetch news articles from yfinance and save new ones to DB."""
        try:
            stock = yf.Ticker(ticker_obj.symbol)
            news_items = stock.news
            if not news_items:
                return []

            new_articles = []
            existing_urls = set(
                NewsArticle.objects.values_list('url', flat=True)
            )

            for item in news_items:
                # Handle both old flat format and new nested content format
                content = item.get('content', item)

                url = (content.get('link')
                       or content.get('url', '')
                       or _nested_get(content, 'canonicalUrl', 'url')
                       or _nested_get(content, 'clickThroughUrl', 'url')
                       or '')
                if not url or url in existing_urls:
                    continue

                title = content.get('title', '')
                if not title:
                    continue

                # Parse published time
                pub_time = (content.get('providerPublishTime')
                            or content.get('pubDate')
                            or content.get('published'))
                if isinstance(pub_time, (int, float)):
                    published_at = datetime.fromtimestamp(pub_time, tz=dt_tz.utc)
                elif isinstance(pub_time, str):
                    try:
                        published_at = datetime.fromisoformat(
                            pub_time.replace('Z', '+00:00')
                        )
                        if published_at.tzinfo is None:
                            published_at = published_at.replace(tzinfo=dt_tz.utc)
                    except ValueError:
                        published_at = timezone.now()
                else:
                    published_at = timezone.now()

                source = (content.get('publisher')
                          or _nested_get(content, 'provider', 'displayName')
                          or content.get('source', ''))

                article = NewsArticle(
                    ticker=ticker_obj,
                    title=title[:500],
                    url=url[:1000],
                    source=source[:200] if source else '',
                    published_at=published_at,
                )
                new_articles.append(article)

            if new_articles:
                NewsArticle.objects.bulk_create(new_articles, ignore_conflicts=True)

            return new_articles
        except Exception:
            logger.exception(f"Failed to fetch news for {ticker_obj.symbol}")
            return []

    @staticmethod
    def analyze_sentiment(article):
        """Analyze sentiment of a news article title using VADER."""
        analyzer = NewsService._get_analyzer()
        scores = analyzer.polarity_scores(article.title)
        compound = scores['compound']

        article.sentiment_score = _to_decimal(compound, places=3)
        if compound >= 0.05:
            article.sentiment_label = 'positive'
        elif compound <= -0.05:
            article.sentiment_label = 'negative'
        else:
            article.sentiment_label = 'neutral'
        article.save(update_fields=['sentiment_score', 'sentiment_label'])
        return article.sentiment_score, article.sentiment_label

    @staticmethod
    def get_aggregate_sentiment(ticker_obj, days=7):
        """Get blended sentiment: 70% ticker-specific + 30% market-wide."""
        cutoff = timezone.now() - timedelta(days=days)

        # Ticker-specific sentiment (yfinance + ticker-matched RSS)
        ticker_result = (
            NewsArticle.objects.filter(
                ticker=ticker_obj,
                published_at__gte=cutoff,
                sentiment_score__isnull=False,
            )
            .aggregate(avg=Avg('sentiment_score'))
        )
        ticker_sentiment = ticker_result['avg']

        # Market-wide sentiment (all RSS articles from recent period)
        market_result = (
            NewsArticle.objects.filter(
                feed_source__isnull=False,
                published_at__gte=cutoff,
                sentiment_score__isnull=False,
            )
            .aggregate(avg=Avg('sentiment_score'))
        )
        market_sentiment = market_result['avg']

        # Blend: 70% ticker, 30% market
        if ticker_sentiment is not None and market_sentiment is not None:
            return Decimal(str(
                float(ticker_sentiment) * 0.7 + float(market_sentiment) * 0.3
            ))
        elif ticker_sentiment is not None:
            return ticker_sentiment
        elif market_sentiment is not None:
            return market_sentiment
        return None

    @staticmethod
    def refresh_news(ticker_obj):
        """Fetch news and analyze sentiment for all new articles."""
        NewsService.fetch_news(ticker_obj)

        # Analyze any unscored articles (includes newly fetched ones)
        unscored = NewsArticle.objects.filter(
            ticker=ticker_obj, sentiment_score__isnull=True
        )
        for article in unscored:
            try:
                NewsService.analyze_sentiment(article)
            except Exception:
                logger.exception(f"Failed to analyze sentiment for: {article.title[:50]}")


# Minimum symbol length to avoid false positives (e.g. "A", "I", "AT")
MIN_SYMBOL_LENGTH = 2


class OptionsDataService:
    """Fetch options chain data from Yahoo Finance and compute directional metrics.

    Uses contrarian interpretation: high put/call ratio (excessive fear) = buying opportunity.
    """

    # Minimum thresholds to avoid noise from illiquid options
    MIN_TOTAL_VOLUME = 100
    MIN_TOTAL_OI = 500

    @staticmethod
    def fetch_options_data(symbol):
        """Fetch options chain and compute all metrics for a ticker.

        Returns a dict of computed metrics, or None if no options available.
        """
        try:
            stock = yf.Ticker(symbol)
            expiry_dates = stock.options
            if not expiry_dates:
                logger.info(f"{symbol}: no options available")
                return None

            # Select expirations within ~30 days
            today = date.today()
            max_date = today + timedelta(days=30)
            near_expirations = [
                exp for exp in expiry_dates
                if date.fromisoformat(exp) <= max_date
            ]

            # Need at least 1 expiration; if none within 30 days, take the nearest
            if not near_expirations:
                near_expirations = [expiry_dates[0]]

            # Aggregate calls and puts across selected expirations
            all_calls = []
            all_puts = []
            for exp_date in near_expirations:
                try:
                    chain = stock.option_chain(exp_date)
                    all_calls.append(chain.calls)
                    all_puts.append(chain.puts)
                except Exception:
                    logger.warning(f"{symbol}: failed to fetch chain for {exp_date}")
                    continue

            if not all_calls or not all_puts:
                return None

            import pandas as pd
            calls_df = pd.concat(all_calls, ignore_index=True)
            puts_df = pd.concat(all_puts, ignore_index=True)

            # Get current price for IV skew calculation
            info = stock.fast_info
            current_price = getattr(info, 'last_price', None)
            if current_price is None:
                return None

            # Compute metrics
            pc_volume = OptionsDataService._put_call_volume_ratio(calls_df, puts_df)
            pc_oi = OptionsDataService._put_call_oi_ratio(calls_df, puts_df)
            iv_skew = OptionsDataService._compute_iv_skew(calls_df, puts_df, current_price)
            max_pain = OptionsDataService._compute_max_pain(calls_df, puts_df)
            unusual = OptionsDataService._detect_unusual_activity(calls_df, puts_df)

            # Compute contrarian sub-score (0-100)
            options_score = OptionsDataService._compute_options_score(pc_volume, pc_oi, iv_skew)
            options_signal = OptionsDataService._options_signal(options_score)

            return {
                'put_call_volume_ratio': pc_volume,
                'put_call_oi_ratio': pc_oi,
                'iv_skew': iv_skew,
                'max_pain': max_pain,
                'current_price': current_price,
                'has_unusual_activity': len(unusual) > 0,
                'unusual_activity_details': unusual,
                'expirations_analyzed': near_expirations,
                'options_score': options_score,
                'options_signal': options_signal,
            }
        except Exception:
            logger.exception(f"Failed to fetch options data for {symbol}")
            return None

    @staticmethod
    def _put_call_volume_ratio(calls_df, puts_df):
        """Compute put/call volume ratio."""
        call_vol = calls_df['volume'].sum()
        put_vol = puts_df['volume'].sum()
        if call_vol < OptionsDataService.MIN_TOTAL_VOLUME:
            return None
        return round(put_vol / call_vol, 3) if call_vol > 0 else None

    @staticmethod
    def _put_call_oi_ratio(calls_df, puts_df):
        """Compute put/call open interest ratio."""
        call_oi = calls_df['openInterest'].sum()
        put_oi = puts_df['openInterest'].sum()
        if call_oi < OptionsDataService.MIN_TOTAL_OI:
            return None
        return round(put_oi / call_oi, 3) if call_oi > 0 else None

    @staticmethod
    def _compute_iv_skew(calls_df, puts_df, current_price):
        """Compute IV skew: avg OTM put IV minus avg OTM call IV.

        Positive skew = puts more expensive (hedging/fear).
        """
        import pandas as pd

        # OTM puts: strike < current price
        otm_puts = puts_df[puts_df['strike'] < current_price].copy()
        otm_puts = otm_puts.dropna(subset=['impliedVolatility'])
        otm_puts = otm_puts[otm_puts['impliedVolatility'] > 0]

        # OTM calls: strike > current price
        otm_calls = calls_df[calls_df['strike'] > current_price].copy()
        otm_calls = otm_calls.dropna(subset=['impliedVolatility'])
        otm_calls = otm_calls[otm_calls['impliedVolatility'] > 0]

        if otm_puts.empty or otm_calls.empty:
            return None

        avg_put_iv = otm_puts['impliedVolatility'].mean()
        avg_call_iv = otm_calls['impliedVolatility'].mean()

        return round(avg_put_iv - avg_call_iv, 4)

    @staticmethod
    def _compute_max_pain(calls_df, puts_df):
        """Calculate max pain: the strike price where total option losses are maximized.

        At max pain, the total intrinsic value of all options is minimized (most expire worthless).
        """
        import pandas as pd

        all_strikes = sorted(set(calls_df['strike'].tolist() + puts_df['strike'].tolist()))
        if not all_strikes:
            return None

        # Build OI lookup
        call_oi = calls_df.groupby('strike')['openInterest'].sum()
        put_oi = puts_df.groupby('strike')['openInterest'].sum()

        min_pain = float('inf')
        max_pain_strike = None

        for strike in all_strikes:
            total_pain = 0.0

            # Pain for call holders at this settlement price
            for s, oi in call_oi.items():
                if strike > s:
                    total_pain += (strike - s) * oi

            # Pain for put holders at this settlement price
            for s, oi in put_oi.items():
                if strike < s:
                    total_pain += (s - strike) * oi

            if total_pain < min_pain:
                min_pain = total_pain
                max_pain_strike = strike

        return round(max_pain_strike, 2) if max_pain_strike is not None else None

    @staticmethod
    def _detect_unusual_activity(calls_df, puts_df):
        """Flag contracts where volume > 5x open interest."""
        unusual = []

        for label, df in [('call', calls_df), ('put', puts_df)]:
            for _, row in df.iterrows():
                oi = row.get('openInterest', 0)
                vol = row.get('volume', 0)
                if oi and oi > 0 and vol > 5 * oi and vol >= 100:
                    unusual.append({
                        'type': label,
                        'strike': float(row['strike']),
                        'volume': int(vol),
                        'open_interest': int(oi),
                        'ratio': round(vol / oi, 1),
                    })

        # Sort by ratio descending, limit to top 10
        unusual.sort(key=lambda x: x['ratio'], reverse=True)
        return unusual[:10]

    @staticmethod
    def _compute_options_score(pc_volume, pc_oi, iv_skew):
        """Compute contrarian options score (0-100).

        High P/C ratio = fear = buying opportunity = high score.
        """
        sub_scores = []
        weights = []

        if pc_volume is not None:
            # Contrarian: P/C ratio of 2.0 → score 90, 1.0 → 50, 0.3 → 10
            score = max(0, min(100, 50 + (pc_volume - 1.0) * 40))
            sub_scores.append(score)
            weights.append(0.40)

        if pc_oi is not None:
            score = max(0, min(100, 50 + (pc_oi - 1.0) * 40))
            sub_scores.append(score)
            weights.append(0.35)

        if iv_skew is not None:
            # Positive skew (puts more expensive) = fear = contrarian bullish
            # Skew of +0.10 → ~70, 0 → 50, -0.10 → ~30
            score = max(0, min(100, 50 + iv_skew * 200))
            sub_scores.append(score)
            weights.append(0.25)

        if not sub_scores:
            return 50  # neutral default

        # Normalize weights
        total_weight = sum(weights)
        weighted = sum(s * w for s, w in zip(sub_scores, weights)) / total_weight
        return int(round(max(0, min(100, weighted))))

    @staticmethod
    def _options_signal(score):
        if score >= 65:
            return 'buy'
        if score <= 35:
            return 'sell'
        return 'hold'


class RSSNewsService:

    @staticmethod
    def _parse_pub_date(text):
        """Parse RSS pubDate string to a timezone-aware datetime."""
        if not text:
            return timezone.now()
        try:
            return parsedate_to_datetime(text)
        except Exception:
            pass
        try:
            dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=dt_tz.utc)
            return dt
        except Exception:
            return timezone.now()

    @staticmethod
    def match_ticker(title):
        """Match known ticker symbols found in the article title.

        Returns a list of matched Ticker objects. Only matches symbols
        with length >= MIN_SYMBOL_LENGTH as whole words to avoid false positives.
        """
        symbols = set(
            Ticker.objects.values_list('symbol', flat=True)
        )
        matched = []
        for symbol in symbols:
            if len(symbol) < MIN_SYMBOL_LENGTH:
                continue
            # Match as whole word, case-sensitive for ticker symbols
            if re.search(r'\b' + re.escape(symbol) + r'\b', title):
                matched.append(symbol)
        if matched:
            return list(Ticker.objects.filter(symbol__in=matched))
        return []

    @staticmethod
    def fetch_feed(feed_source):
        """Fetch and parse a single RSS feed, saving new articles."""
        try:
            resp = requests.get(feed_source.url, timeout=15, headers={
                'User-Agent': 'MyStocks/1.0',
            })
            resp.raise_for_status()
        except Exception:
            logger.exception(f"Failed to fetch RSS feed: {feed_source.name}")
            return []

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError:
            logger.exception(f"Failed to parse RSS XML: {feed_source.name}")
            return []

        # Handle both RSS 2.0 and Atom feeds
        items = root.findall('.//item')
        if not items:
            # Try Atom format
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            items = root.findall('.//atom:entry', ns)

        existing_urls = set(NewsArticle.objects.values_list('url', flat=True))
        new_articles = []

        for item in items:
            # RSS 2.0 format
            title_el = item.find('title')
            link_el = item.find('link')
            pub_date_el = item.find('pubDate')

            if title_el is None or link_el is None:
                # Try Atom format
                ns = {'atom': 'http://www.w3.org/2005/Atom'}
                title_el = item.find('atom:title', ns)
                link_el = item.find('atom:link', ns)
                pub_date_el = item.find('atom:published', ns) or item.find('atom:updated', ns)

            title = ''
            url = ''

            if title_el is not None:
                title = (title_el.text or '').strip()
            if link_el is not None:
                url = (link_el.text or link_el.get('href', '')).strip()

            if not title or not url or url in existing_urls:
                continue

            published_at = RSSNewsService._parse_pub_date(
                pub_date_el.text.strip() if pub_date_el is not None and pub_date_el.text else None
            )

            # Try to match ticker symbols in title
            matched_tickers = RSSNewsService.match_ticker(title)

            if matched_tickers:
                # Create one article per matched ticker
                for ticker in matched_tickers:
                    if url not in existing_urls:
                        article = NewsArticle(
                            ticker=ticker,
                            feed_source=feed_source,
                            title=title[:500],
                            url=url[:1000],
                            source=feed_source.name[:200],
                            published_at=published_at,
                        )
                        new_articles.append(article)
                        existing_urls.add(url)
            else:
                # General article, no ticker match
                article = NewsArticle(
                    ticker=None,
                    feed_source=feed_source,
                    title=title[:500],
                    url=url[:1000],
                    source=feed_source.name[:200],
                    published_at=published_at,
                )
                new_articles.append(article)
                existing_urls.add(url)

        if new_articles:
            NewsArticle.objects.bulk_create(new_articles, ignore_conflicts=True)

        # Analyze sentiment for new articles
        for article in new_articles:
            if article.pk:
                try:
                    NewsService.analyze_sentiment(article)
                except Exception:
                    logger.exception(f"Failed to analyze RSS sentiment: {article.title[:50]}")

        # Update last_fetched
        feed_source.last_fetched = timezone.now()
        feed_source.save(update_fields=['last_fetched'])

        return new_articles

    @staticmethod
    def fetch_all_feeds():
        """Fetch all enabled RSS feeds."""
        feeds = RSSFeedSource.objects.filter(enabled=True)
        total_articles = []
        for feed in feeds:
            try:
                articles = RSSNewsService.fetch_feed(feed)
                total_articles.extend(articles)
                logger.info(f"Fetched {len(articles)} articles from {feed.name}")
            except Exception:
                logger.exception(f"Failed to fetch feed: {feed.name}")
        return total_articles
