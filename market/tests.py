from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from market.models import NewsArticle, PriceHistory, QuarterlyEarning, RSSFeedSource
from market.services import NewsService, OptionsDataService, RSSNewsService, StockDataService
from market.services import _compute_growth_pct
from portfolio.models import Lot, Portfolio, Ticker


class LoggedInTestCase(TestCase):
    """Base test class that provides an authenticated client."""
    def setUp(self):
        self.user = User.objects.create_user('testuser', password='testpass')
        self.client = Client()
        self.client.force_login(self.user)


class PriceHistoryModelTest(TestCase):
    def setUp(self):
        self.ticker = Ticker.objects.create(symbol='AAPL', last_price=Decimal('178.50'))

    def test_create_price_history(self):
        ph = PriceHistory.objects.create(
            ticker=self.ticker,
            date=date(2024, 1, 15),
            open=Decimal('175.00'),
            high=Decimal('180.00'),
            low=Decimal('174.00'),
            close=Decimal('178.50'),
            volume=58000000,
        )
        self.assertEqual(str(ph), 'AAPL 2024-01-15 close=178.50')

    def test_unique_together(self):
        PriceHistory.objects.create(
            ticker=self.ticker, date=date(2024, 1, 15),
            open=Decimal('175'), high=Decimal('180'), low=Decimal('174'),
            close=Decimal('178.50'), volume=58000000,
        )
        with self.assertRaises(Exception):
            PriceHistory.objects.create(
                ticker=self.ticker, date=date(2024, 1, 15),
                open=Decimal('175'), high=Decimal('180'), low=Decimal('174'),
                close=Decimal('179.00'), volume=58000000,
            )

    def test_ordering(self):
        PriceHistory.objects.create(
            ticker=self.ticker, date=date(2024, 1, 10),
            open=Decimal('170'), high=Decimal('175'), low=Decimal('169'),
            close=Decimal('174'), volume=50000000,
        )
        PriceHistory.objects.create(
            ticker=self.ticker, date=date(2024, 1, 15),
            open=Decimal('175'), high=Decimal('180'), low=Decimal('174'),
            close=Decimal('178'), volume=58000000,
        )
        prices = list(PriceHistory.objects.filter(ticker=self.ticker))
        self.assertEqual(prices[0].date, date(2024, 1, 15))  # newest first


def _mock_yf_ticker(info=None, history_df=None):
    """Create a mock yfinance Ticker object."""
    mock = MagicMock()
    mock.info = info or {}
    if history_df is not None:
        mock.history.return_value = history_df
    else:
        import pandas as pd
        mock.history.return_value = pd.DataFrame()
    mock.fast_info = MagicMock()
    mock.fast_info.last_price = None
    mock.fast_info.previous_close = None
    mock.fast_info.last_volume = None
    return mock


class StockDataServiceTest(TestCase):
    def setUp(self):
        self.ticker = Ticker.objects.create(symbol='AAPL')

    @patch('market.services.yf.Ticker')
    def test_get_quote(self, mock_yf):
        mock_yf.return_value = _mock_yf_ticker(info={
            'regularMarketPrice': 178.50,
            'regularMarketPreviousClose': 176.00,
            'regularMarketVolume': 58000000,
        })
        quote = StockDataService.get_quote('AAPL')
        self.assertIsNotNone(quote)
        self.assertEqual(quote['price'], Decimal('178.50'))
        self.assertEqual(quote['prev_close'], Decimal('176.00'))
        self.assertIsNotNone(quote['day_change'])

    @patch('market.services.yf.Ticker')
    def test_get_quote_failure_returns_none(self, mock_yf):
        mock_yf.side_effect = Exception('API error')
        quote = StockDataService.get_quote('BAD')
        self.assertIsNone(quote)

    @patch('market.services.yf.Ticker')
    def test_get_history(self, mock_yf):
        import pandas as pd
        import numpy as np
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        df = pd.DataFrame({
            'Open': [170.0, 171.0, 172.0, 173.0, 174.0],
            'High': [175.0, 176.0, 177.0, 178.0, 179.0],
            'Low': [169.0, 170.0, 171.0, 172.0, 173.0],
            'Close': [174.0, 175.0, 176.0, 177.0, 178.0],
            'Volume': [50000000] * 5,
        }, index=dates)
        mock_yf.return_value = _mock_yf_ticker(history_df=df)

        history = StockDataService.get_history('AAPL', period='1mo')
        self.assertEqual(len(history), 5)
        self.assertEqual(history[0]['close'], Decimal('174.00'))

    @patch('market.services.yf.Ticker')
    def test_get_company_info(self, mock_yf):
        mock_yf.return_value = _mock_yf_ticker(info={
            'shortName': 'Apple Inc.',
            'sector': 'Technology',
            'marketCap': 2800000000000,
            'trailingPE': 28.5,
            'dividendYield': 0.0055,
            'fiftyTwoWeekHigh': 199.62,
            'fiftyTwoWeekLow': 124.17,
            'averageVolume': 55000000,
        })
        info = StockDataService.get_company_info('AAPL')
        self.assertEqual(info['company_name'], 'Apple Inc.')
        self.assertEqual(info['sector'], 'Technology')
        self.assertEqual(info['market_cap'], 2800000000000)

    @patch('market.services.yf.Ticker')
    def test_refresh_ticker(self, mock_yf):
        import pandas as pd
        dates = pd.date_range('2024-01-01', periods=3, freq='B')
        df = pd.DataFrame({
            'Open': [170.0, 171.0, 172.0],
            'High': [175.0, 176.0, 177.0],
            'Low': [169.0, 170.0, 171.0],
            'Close': [174.0, 175.0, 176.0],
            'Volume': [50000000] * 3,
        }, index=dates)
        mock_yf.return_value = _mock_yf_ticker(
            info={
                'regularMarketPrice': 178.50,
                'regularMarketPreviousClose': 176.00,
                'shortName': 'Apple Inc.',
                'sector': 'Technology',
                'marketCap': 2800000000000,
            },
            history_df=df,
        )

        StockDataService.refresh_ticker(self.ticker)
        self.ticker.refresh_from_db()
        self.assertEqual(self.ticker.last_price, Decimal('178.50'))
        self.assertEqual(self.ticker.company_name, 'Apple Inc.')
        self.assertIsNotNone(self.ticker.last_updated)
        self.assertEqual(PriceHistory.objects.filter(ticker=self.ticker).count(), 3)


class TickerDetailViewTest(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.ticker = Ticker.objects.create(
            symbol='AAPL', company_name='Apple Inc.',
            last_price=Decimal('178.50'),
            last_updated=timezone.now(),
        )
        PriceHistory.objects.create(
            ticker=self.ticker, date=date(2024, 1, 15),
            open=Decimal('175'), high=Decimal('180'), low=Decimal('174'),
            close=Decimal('178.50'), volume=58000000,
        )

    def test_detail_page_loads(self):
        response = self.client.get(reverse('ticker_detail', args=['AAPL']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'AAPL')
        self.assertContains(response, 'Apple Inc.')

    def test_detail_case_insensitive(self):
        response = self.client.get(reverse('ticker_detail', args=['aapl']))
        self.assertEqual(response.status_code, 200)

    def test_detail_404(self):
        response = self.client.get(reverse('ticker_detail', args=['ZZZZ']))
        self.assertEqual(response.status_code, 404)

    def test_shows_holdings(self):
        portfolio = Portfolio.objects.create(name='Test', user=self.user)
        Lot.objects.create(
            portfolio=portfolio, ticker=self.ticker,
            shares=Decimal('100'), cost_basis=Decimal('150'),
            purchase_date=date(2024, 1, 1),
        )
        response = self.client.get(reverse('ticker_detail', args=['AAPL']))
        self.assertContains(response, 'Test')
        self.assertContains(response, '100')


class ChartDataViewTest(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.ticker = Ticker.objects.create(symbol='AAPL')
        # Create enough data points for '5d' period (threshold: 5 * 0.5 = 2.5)
        for i in range(5):
            PriceHistory.objects.create(
                ticker=self.ticker,
                date=date(2024, 1, 10 + i),
                open=Decimal('170'), high=Decimal('175'), low=Decimal('169'),
                close=Decimal(str(170 + i)),
                volume=50000000,
            )

    def test_chart_data_returns_json(self):
        response = self.client.get(
            reverse('chart_data', args=['AAPL']), {'period': '5d'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('labels', data)
        self.assertIn('prices', data)
        self.assertEqual(len(data['labels']), 5)


class RefreshViewTest(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.ticker = Ticker.objects.create(symbol='AAPL')

    def test_refresh_requires_post(self):
        response = self.client.get(reverse('refresh_ticker', args=['AAPL']))
        self.assertEqual(response.status_code, 405)

    @patch('market.views.StockDataService.refresh_ticker')
    def test_refresh_single_ticker(self, mock_refresh):
        response = self.client.post(reverse('refresh_ticker', args=['AAPL']))
        self.assertEqual(response.status_code, 200)
        mock_refresh.assert_called_once()

    def test_refresh_all_requires_post(self):
        response = self.client.get(reverse('refresh_all'))
        self.assertEqual(response.status_code, 405)

    @patch('market.views.StockDataService.refresh_all')
    def test_refresh_all(self, mock_refresh_all):
        mock_refresh_all.return_value = [('AAPL', True)]
        response = self.client.post(reverse('refresh_all'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['refreshed'], 1)


class NewsArticleModelTest(TestCase):
    def setUp(self):
        self.ticker = Ticker.objects.create(symbol='AAPL')

    def test_create_article(self):
        article = NewsArticle.objects.create(
            ticker=self.ticker,
            title='Apple reports record earnings',
            url='https://example.com/article1',
            source='Reuters',
            published_at=timezone.now(),
        )
        self.assertIn('AAPL', str(article))
        self.assertIn('Apple reports', str(article))

    def test_unique_together(self):
        NewsArticle.objects.create(
            ticker=self.ticker,
            title='Article 1',
            url='https://example.com/same-url',
            published_at=timezone.now(),
        )
        with self.assertRaises(Exception):
            NewsArticle.objects.create(
                ticker=self.ticker,
                title='Article 2',
                url='https://example.com/same-url',
                published_at=timezone.now(),
            )

    def test_ordering(self):
        from datetime import timedelta
        now = timezone.now()
        NewsArticle.objects.create(
            ticker=self.ticker, title='Old', url='https://example.com/old',
            published_at=now - timedelta(days=2),
        )
        NewsArticle.objects.create(
            ticker=self.ticker, title='New', url='https://example.com/new',
            published_at=now,
        )
        articles = list(NewsArticle.objects.filter(ticker=self.ticker))
        self.assertEqual(articles[0].title, 'New')


class NewsServiceTest(TestCase):
    def setUp(self):
        self.ticker = Ticker.objects.create(symbol='AAPL')

    def test_analyze_sentiment_positive(self):
        article = NewsArticle.objects.create(
            ticker=self.ticker,
            title='Apple stock surges to record high after amazing earnings beat',
            url='https://example.com/positive',
            published_at=timezone.now(),
        )
        score, label = NewsService.analyze_sentiment(article)
        self.assertIsNotNone(score)
        self.assertEqual(label, 'positive')
        self.assertGreater(float(score), 0)

    def test_analyze_sentiment_negative(self):
        article = NewsArticle.objects.create(
            ticker=self.ticker,
            title='Apple stock crashes amid terrible losses and horrible outlook',
            url='https://example.com/negative',
            published_at=timezone.now(),
        )
        score, label = NewsService.analyze_sentiment(article)
        self.assertEqual(label, 'negative')
        self.assertLess(float(score), 0)

    def test_analyze_sentiment_neutral(self):
        article = NewsArticle.objects.create(
            ticker=self.ticker,
            title='Apple to hold annual meeting next week',
            url='https://example.com/neutral',
            published_at=timezone.now(),
        )
        score, label = NewsService.analyze_sentiment(article)
        self.assertIn(label, ('neutral', 'positive', 'negative'))

    def test_aggregate_sentiment(self):
        now = timezone.now()
        for i in range(3):
            a = NewsArticle.objects.create(
                ticker=self.ticker,
                title='Great positive amazing news',
                url=f'https://example.com/art{i}',
                published_at=now,
                sentiment_score=Decimal('0.500'),
                sentiment_label='positive',
            )
        avg = NewsService.get_aggregate_sentiment(self.ticker, days=7)
        self.assertIsNotNone(avg)
        self.assertAlmostEqual(float(avg), 0.5, places=1)

    def test_aggregate_sentiment_no_articles(self):
        avg = NewsService.get_aggregate_sentiment(self.ticker, days=7)
        self.assertIsNone(avg)

    @patch('market.services.yf.Ticker')
    def test_fetch_news(self, mock_yf):
        import time
        mock_ticker = MagicMock()
        mock_ticker.news = [
            {
                'title': 'Apple beats expectations',
                'link': 'https://example.com/news1',
                'publisher': 'Reuters',
                'providerPublishTime': int(time.time()),
            },
            {
                'title': 'iPhone sales strong',
                'link': 'https://example.com/news2',
                'publisher': 'Bloomberg',
                'providerPublishTime': int(time.time()),
            },
        ]
        mock_yf.return_value = mock_ticker
        articles = NewsService.fetch_news(self.ticker)
        self.assertEqual(len(articles), 2)
        self.assertEqual(NewsArticle.objects.filter(ticker=self.ticker).count(), 2)

    @patch('market.services.yf.Ticker')
    def test_fetch_news_skips_duplicates(self, mock_yf):
        import time
        NewsArticle.objects.create(
            ticker=self.ticker,
            title='Existing',
            url='https://example.com/existing',
            published_at=timezone.now(),
        )
        mock_ticker = MagicMock()
        mock_ticker.news = [
            {
                'title': 'Existing article',
                'link': 'https://example.com/existing',
                'publisher': 'Reuters',
                'providerPublishTime': int(time.time()),
            },
        ]
        mock_yf.return_value = mock_ticker
        articles = NewsService.fetch_news(self.ticker)
        self.assertEqual(len(articles), 0)


class NewsPageViewTest(LoggedInTestCase):
    def test_news_page_loads(self):
        response = self.client.get(reverse('news_feed'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'News Feed')

    def test_news_page_shows_articles(self):
        ticker = Ticker.objects.create(symbol='AAPL')
        portfolio = Portfolio.objects.create(name='Test', user=self.user)
        Lot.objects.create(
            portfolio=portfolio, ticker=ticker,
            shares=Decimal('10'), cost_basis=Decimal('150'),
            purchase_date=date(2024, 1, 1),
        )
        NewsArticle.objects.create(
            ticker=ticker,
            title='Apple new product launch',
            url='https://example.com/launch',
            published_at=timezone.now(),
            sentiment_label='positive',
            sentiment_score=Decimal('0.500'),
        )
        response = self.client.get(reverse('news_feed'))
        self.assertContains(response, 'Apple new product launch')
        self.assertContains(response, 'AAPL')


class SettingsViewTest(LoggedInTestCase):
    def test_settings_page_loads(self):
        response = self.client.get(reverse('settings'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Settings')
        self.assertContains(response, 'VADER')

    def test_settings_shows_feeds(self):
        feed = RSSFeedSource.objects.create(
            name='Test Feed', url='https://example.com/rss',
            category='stock', enabled=True,
        )
        response = self.client.get(reverse('settings'))
        self.assertContains(response, 'Test Feed')
        self.assertContains(response, 'RSS News Feeds')


class RSSFeedSourceModelTest(TestCase):
    def test_create_feed(self):
        feed = RSSFeedSource.objects.create(
            name='CNBC Markets',
            url='https://example.com/cnbc-rss',
            category='stock',
        )
        self.assertTrue(feed.enabled)
        self.assertIsNone(feed.last_fetched)
        self.assertEqual(str(feed), 'CNBC Markets (stock)')

    def test_unique_url(self):
        RSSFeedSource.objects.create(
            name='Feed 1', url='https://example.com/feed',
        )
        with self.assertRaises(Exception):
            RSSFeedSource.objects.create(
                name='Feed 2', url='https://example.com/feed',
            )

    def test_category_choices(self):
        stock = RSSFeedSource.objects.create(
            name='Stock', url='https://example.com/stock', category='stock',
        )
        geo = RSSFeedSource.objects.create(
            name='Geo', url='https://example.com/geo', category='geopolitical',
        )
        self.assertEqual(stock.get_category_display(), 'Stock/Market')
        self.assertEqual(geo.get_category_display(), 'Geopolitical')


class NewsArticleNullableTickerTest(TestCase):
    def test_article_without_ticker(self):
        feed = RSSFeedSource.objects.create(
            name='Test', url='https://example.com/rss',
        )
        article = NewsArticle.objects.create(
            ticker=None,
            feed_source=feed,
            title='Market rallies on economic data',
            url='https://example.com/general-news',
            published_at=timezone.now(),
        )
        self.assertIsNone(article.ticker)
        self.assertIn('General', str(article))

    def test_unique_url_constraint(self):
        ticker = Ticker.objects.create(symbol='AAPL')
        NewsArticle.objects.create(
            ticker=ticker,
            title='Article 1',
            url='https://example.com/unique-test',
            published_at=timezone.now(),
        )
        with self.assertRaises(Exception):
            NewsArticle.objects.create(
                ticker=None,
                title='Article 2',
                url='https://example.com/unique-test',
                published_at=timezone.now(),
            )


RSS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
    <title>Test Feed</title>
    <item>
        <title>AAPL hits new high after strong earnings</title>
        <link>https://example.com/aapl-article</link>
        <pubDate>Sat, 22 Feb 2026 12:00:00 GMT</pubDate>
    </item>
    <item>
        <title>Global markets rally on trade deal</title>
        <link>https://example.com/market-article</link>
        <pubDate>Sat, 22 Feb 2026 11:00:00 GMT</pubDate>
    </item>
    <item>
        <title>Duplicate article</title>
        <link>https://example.com/existing</link>
        <pubDate>Sat, 22 Feb 2026 10:00:00 GMT</pubDate>
    </item>
</channel>
</rss>"""


class RSSNewsServiceTest(TestCase):
    def setUp(self):
        self.ticker = Ticker.objects.create(symbol='AAPL', company_name='Apple Inc.')
        self.feed = RSSFeedSource.objects.create(
            name='Test Feed', url='https://example.com/test-rss',
            category='stock', enabled=True,
        )
        # Pre-existing article to test dedup
        NewsArticle.objects.create(
            ticker=self.ticker,
            title='Existing',
            url='https://example.com/existing',
            published_at=timezone.now(),
        )

    @patch('market.services.requests.get')
    def test_fetch_feed_creates_articles(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.content = RSS_XML
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        articles = RSSNewsService.fetch_feed(self.feed)
        # 3 items in XML, 1 is a duplicate => 2 new articles
        self.assertEqual(len(articles), 2)

    @patch('market.services.requests.get')
    def test_fetch_feed_matches_ticker(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.content = RSS_XML
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        articles = RSSNewsService.fetch_feed(self.feed)
        # First article mentions AAPL, should be ticker-linked
        aapl_articles = [a for a in articles if a.ticker and a.ticker.symbol == 'AAPL']
        general_articles = [a for a in articles if a.ticker is None]
        self.assertEqual(len(aapl_articles), 1)
        self.assertEqual(len(general_articles), 1)

    @patch('market.services.requests.get')
    def test_fetch_feed_skips_duplicates(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.content = RSS_XML
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        RSSNewsService.fetch_feed(self.feed)
        # Total articles: 1 existing + 2 new = 3
        self.assertEqual(NewsArticle.objects.count(), 3)

    @patch('market.services.requests.get')
    def test_fetch_feed_updates_last_fetched(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.content = RSS_XML
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        self.assertIsNone(self.feed.last_fetched)
        RSSNewsService.fetch_feed(self.feed)
        self.feed.refresh_from_db()
        self.assertIsNotNone(self.feed.last_fetched)

    @patch('market.services.requests.get')
    def test_fetch_feed_handles_http_error(self, mock_get):
        mock_get.side_effect = Exception('Connection refused')
        articles = RSSNewsService.fetch_feed(self.feed)
        self.assertEqual(len(articles), 0)

    def test_match_ticker_finds_symbol(self):
        matches = RSSNewsService.match_ticker('AAPL hits new high today')
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].symbol, 'AAPL')

    def test_match_ticker_no_match(self):
        matches = RSSNewsService.match_ticker('Global markets rally on trade deal')
        self.assertEqual(len(matches), 0)

    def test_match_ticker_ignores_short_symbols(self):
        Ticker.objects.create(symbol='A')
        matches = RSSNewsService.match_ticker('A great day for markets')
        # Should NOT match single-letter symbol 'A'
        self.assertEqual(len(matches), 0)

    @patch('market.services.requests.get')
    def test_fetch_all_feeds(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.content = RSS_XML
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        # Disable all feeds except our test feed
        RSSFeedSource.objects.exclude(pk=self.feed.pk).update(enabled=False)
        articles = RSSNewsService.fetch_all_feeds()
        self.assertTrue(len(articles) >= 0)
        # Only our test feed should be fetched
        mock_get.assert_called_once_with(
            self.feed.url, timeout=15, headers={'User-Agent': 'MyStocks/1.0'}
        )


class ToggleFeedViewTest(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.feed = RSSFeedSource.objects.create(
            name='Test Feed', url='https://example.com/toggle-rss',
            category='stock', enabled=True,
        )

    def test_toggle_requires_post(self):
        response = self.client.get(reverse('toggle_feed', args=[self.feed.pk]))
        self.assertEqual(response.status_code, 405)

    def test_toggle_disables_feed(self):
        response = self.client.post(reverse('toggle_feed', args=[self.feed.pk]))
        self.assertEqual(response.status_code, 200)
        self.feed.refresh_from_db()
        self.assertFalse(self.feed.enabled)

    def test_toggle_enables_feed(self):
        self.feed.enabled = False
        self.feed.save()
        response = self.client.post(reverse('toggle_feed', args=[self.feed.pk]))
        self.assertEqual(response.status_code, 200)
        self.feed.refresh_from_db()
        self.assertTrue(self.feed.enabled)


class NewsFeedCategoryFilterTest(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.ticker = Ticker.objects.create(symbol='AAPL')
        self.feed_stock = RSSFeedSource.objects.create(
            name='Stock Feed', url='https://example.com/stock-rss', category='stock',
        )
        self.feed_geo = RSSFeedSource.objects.create(
            name='Geo Feed', url='https://example.com/geo-rss', category='geopolitical',
        )
        now = timezone.now()
        # Ticker-specific article (no feed source)
        NewsArticle.objects.create(
            ticker=self.ticker, title='AAPL earnings beat',
            url='https://example.com/ticker-art', published_at=now,
        )
        # Stock RSS article
        NewsArticle.objects.create(
            ticker=None, feed_source=self.feed_stock, title='Markets rally today',
            url='https://example.com/stock-art', published_at=now,
        )
        # Geopolitical RSS article
        NewsArticle.objects.create(
            ticker=None, feed_source=self.feed_geo, title='Trade deal signed',
            url='https://example.com/geo-art', published_at=now,
        )

    def test_all_category(self):
        response = self.client.get(reverse('news_feed'))
        self.assertContains(response, 'AAPL earnings beat')
        self.assertContains(response, 'Markets rally today')
        self.assertContains(response, 'Trade deal signed')

    def test_stock_category(self):
        response = self.client.get(reverse('news_feed') + '?category=stock')
        self.assertContains(response, 'Markets rally today')
        self.assertContains(response, 'AAPL earnings beat')
        self.assertNotContains(response, 'Trade deal signed')

    def test_geopolitical_category(self):
        response = self.client.get(reverse('news_feed') + '?category=geopolitical')
        self.assertContains(response, 'Trade deal signed')
        self.assertNotContains(response, 'Markets rally today')

    def test_ticker_category(self):
        response = self.client.get(reverse('news_feed') + '?category=ticker')
        self.assertContains(response, 'AAPL earnings beat')
        self.assertNotContains(response, 'Markets rally today')
        self.assertNotContains(response, 'Trade deal signed')


class BlendedSentimentTest(TestCase):
    def setUp(self):
        self.ticker = Ticker.objects.create(symbol='AAPL')
        self.feed = RSSFeedSource.objects.create(
            name='Test Feed', url='https://example.com/blend-rss',
        )

    def test_blended_both_sources(self):
        now = timezone.now()
        # Ticker-specific articles: avg 0.5
        for i in range(3):
            NewsArticle.objects.create(
                ticker=self.ticker, title=f'Good news {i}',
                url=f'https://example.com/ticker-{i}', published_at=now,
                sentiment_score=Decimal('0.500'), sentiment_label='positive',
            )
        # Market-wide RSS articles: avg -0.2
        for i in range(3):
            NewsArticle.objects.create(
                ticker=None, feed_source=self.feed, title=f'Bad market {i}',
                url=f'https://example.com/market-{i}', published_at=now,
                sentiment_score=Decimal('-0.200'), sentiment_label='negative',
            )
        blended = NewsService.get_aggregate_sentiment(self.ticker, days=7)
        # Expected: 0.5 * 0.7 + (-0.2) * 0.3 = 0.35 - 0.06 = 0.29
        self.assertIsNotNone(blended)
        self.assertAlmostEqual(float(blended), 0.29, places=1)

    def test_ticker_only_sentiment(self):
        now = timezone.now()
        NewsArticle.objects.create(
            ticker=self.ticker, title='Good news',
            url='https://example.com/t-only', published_at=now,
            sentiment_score=Decimal('0.500'), sentiment_label='positive',
        )
        result = NewsService.get_aggregate_sentiment(self.ticker, days=7)
        self.assertAlmostEqual(float(result), 0.5, places=1)

    def test_market_only_sentiment(self):
        now = timezone.now()
        NewsArticle.objects.create(
            ticker=None, feed_source=self.feed, title='Market news',
            url='https://example.com/m-only', published_at=now,
            sentiment_score=Decimal('0.300'), sentiment_label='positive',
        )
        result = NewsService.get_aggregate_sentiment(self.ticker, days=7)
        self.assertAlmostEqual(float(result), 0.3, places=1)


def _make_options_df(strikes, volumes, ois, ivs):
    """Helper to create a mock options DataFrame."""
    import pandas as pd
    return pd.DataFrame({
        'strike': strikes,
        'volume': volumes,
        'openInterest': ois,
        'impliedVolatility': ivs,
    })


class OptionsDataServicePutCallRatioTest(TestCase):
    def test_volume_ratio(self):
        calls = _make_options_df([100, 105], [500, 300], [1000, 800], [0.3, 0.25])
        puts = _make_options_df([95, 90], [600, 400], [900, 700], [0.35, 0.4])
        ratio = OptionsDataService._put_call_volume_ratio(calls, puts)
        # put_vol=1000, call_vol=800 → 1.25
        self.assertAlmostEqual(ratio, 1.25, places=2)

    def test_volume_ratio_low_volume_returns_none(self):
        calls = _make_options_df([100], [10], [1000], [0.3])
        puts = _make_options_df([95], [20], [900], [0.35])
        ratio = OptionsDataService._put_call_volume_ratio(calls, puts)
        self.assertIsNone(ratio)

    def test_oi_ratio(self):
        calls = _make_options_df([100, 105], [500, 300], [1000, 500], [0.3, 0.25])
        puts = _make_options_df([95, 90], [600, 400], [800, 400], [0.35, 0.4])
        ratio = OptionsDataService._put_call_oi_ratio(calls, puts)
        # put_oi=1200, call_oi=1500 → 0.8
        self.assertAlmostEqual(ratio, 0.8, places=2)

    def test_oi_ratio_low_oi_returns_none(self):
        calls = _make_options_df([100], [500], [100], [0.3])
        puts = _make_options_df([95], [600], [80], [0.35])
        ratio = OptionsDataService._put_call_oi_ratio(calls, puts)
        self.assertIsNone(ratio)


class OptionsIVSkewTest(TestCase):
    def test_positive_skew(self):
        # Current price = 100; OTM puts (strike<100), OTM calls (strike>100)
        calls = _make_options_df([105, 110], [100, 100], [500, 500], [0.25, 0.20])
        puts = _make_options_df([95, 90], [100, 100], [500, 500], [0.40, 0.45])
        skew = OptionsDataService._compute_iv_skew(calls, puts, 100.0)
        # avg put IV = 0.425, avg call IV = 0.225, skew = 0.20
        self.assertAlmostEqual(skew, 0.20, places=2)
        self.assertGreater(skew, 0)  # positive = puts more expensive

    def test_negative_skew(self):
        calls = _make_options_df([105, 110], [100, 100], [500, 500], [0.45, 0.50])
        puts = _make_options_df([95, 90], [100, 100], [500, 500], [0.20, 0.25])
        skew = OptionsDataService._compute_iv_skew(calls, puts, 100.0)
        self.assertLess(skew, 0)

    def test_no_otm_options_returns_none(self):
        # All calls ITM (strike < current_price)
        calls = _make_options_df([90, 95], [100, 100], [500, 500], [0.3, 0.25])
        puts = _make_options_df([105, 110], [100, 100], [500, 500], [0.35, 0.4])
        skew = OptionsDataService._compute_iv_skew(calls, puts, 100.0)
        self.assertIsNone(skew)


class OptionsMaxPainTest(TestCase):
    def test_max_pain_calculation(self):
        calls = _make_options_df([95, 100, 105], [100, 200, 100], [1000, 2000, 500], [0.3, 0.25, 0.2])
        puts = _make_options_df([95, 100, 105], [100, 200, 100], [500, 2000, 1000], [0.35, 0.3, 0.25])
        pain = OptionsDataService._compute_max_pain(calls, puts)
        self.assertIsNotNone(pain)
        self.assertIn(pain, [95.0, 100.0, 105.0])

    def test_empty_strikes_returns_none(self):
        import pandas as pd
        calls = pd.DataFrame({'strike': [], 'volume': [], 'openInterest': [], 'impliedVolatility': []})
        puts = pd.DataFrame({'strike': [], 'volume': [], 'openInterest': [], 'impliedVolatility': []})
        self.assertIsNone(OptionsDataService._compute_max_pain(calls, puts))


class OptionsUnusualActivityTest(TestCase):
    def test_detects_unusual(self):
        # Volume > 5x OI and volume >= 100
        calls = _make_options_df([100], [600], [100], [0.3])
        puts = _make_options_df([95], [50], [500], [0.35])
        unusual = OptionsDataService._detect_unusual_activity(calls, puts)
        self.assertEqual(len(unusual), 1)
        self.assertEqual(unusual[0]['type'], 'call')
        self.assertEqual(unusual[0]['strike'], 100.0)

    def test_no_unusual_when_ratio_low(self):
        calls = _make_options_df([100], [200], [500], [0.3])
        puts = _make_options_df([95], [100], [500], [0.35])
        unusual = OptionsDataService._detect_unusual_activity(calls, puts)
        self.assertEqual(len(unusual), 0)

    def test_ignores_low_volume(self):
        # High ratio but volume < 100
        calls = _make_options_df([100], [50], [5], [0.3])
        puts = _make_options_df([95], [10], [1], [0.35])
        unusual = OptionsDataService._detect_unusual_activity(calls, puts)
        self.assertEqual(len(unusual), 0)


class OptionsScoreTest(TestCase):
    def test_high_pc_ratio_scores_high(self):
        # Contrarian: high P/C = fear = bullish = high score
        score = OptionsDataService._compute_options_score(2.0, 1.5, 0.10)
        self.assertGreater(score, 65)

    def test_low_pc_ratio_scores_low(self):
        score = OptionsDataService._compute_options_score(0.3, 0.5, -0.10)
        self.assertLess(score, 35)

    def test_neutral_score(self):
        score = OptionsDataService._compute_options_score(1.0, 1.0, 0.0)
        self.assertEqual(score, 50)

    def test_none_inputs_returns_default(self):
        score = OptionsDataService._compute_options_score(None, None, None)
        self.assertEqual(score, 50)

    def test_partial_data(self):
        # Only volume ratio available
        score = OptionsDataService._compute_options_score(1.5, None, None)
        self.assertGreater(score, 50)

    def test_signal_buy(self):
        self.assertEqual(OptionsDataService._options_signal(80), 'buy')

    def test_signal_sell(self):
        self.assertEqual(OptionsDataService._options_signal(20), 'sell')

    def test_signal_hold(self):
        self.assertEqual(OptionsDataService._options_signal(50), 'hold')


class OptionsFetchIntegrationTest(TestCase):
    @patch('market.services.yf.Ticker')
    def test_fetch_no_options_returns_none(self, mock_ticker_cls):
        mock_stock = MagicMock()
        mock_stock.options = ()
        mock_ticker_cls.return_value = mock_stock
        result = OptionsDataService.fetch_options_data('NOOPT')
        self.assertIsNone(result)

    @patch('market.services.yf.Ticker')
    def test_fetch_returns_metrics(self, mock_ticker_cls):
        import pandas as pd

        calls_df = _make_options_df(
            [105, 110, 115], [200, 150, 100], [1000, 800, 500], [0.25, 0.22, 0.20]
        )
        puts_df = _make_options_df(
            [95, 90, 85], [300, 200, 100], [900, 700, 400], [0.35, 0.40, 0.45]
        )
        chain = MagicMock()
        chain.calls = calls_df
        chain.puts = puts_df

        mock_stock = MagicMock()
        mock_stock.options = ('2026-04-01',)
        mock_stock.option_chain.return_value = chain
        mock_stock.fast_info.last_price = 100.0
        mock_ticker_cls.return_value = mock_stock

        result = OptionsDataService.fetch_options_data('AAPL')
        self.assertIsNotNone(result)
        self.assertIn('put_call_volume_ratio', result)
        self.assertIn('put_call_oi_ratio', result)
        self.assertIn('iv_skew', result)
        self.assertIn('max_pain', result)
        self.assertIn('options_score', result)
        self.assertIn('options_signal', result)
        self.assertIsInstance(result['options_score'], int)
        self.assertIn(result['options_signal'], ('buy', 'hold', 'sell'))


class TickerDetailWhaleTest(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.ticker = Ticker.objects.create(
            symbol='AAPL', company_name='Apple Inc.',
            last_price=Decimal('178.50'), last_updated=timezone.now(),
        )
        PriceHistory.objects.create(
            ticker=self.ticker, date=date(2024, 1, 15),
            open=Decimal('175'), high=Decimal('180'), low=Decimal('174'),
            close=Decimal('178.50'), volume=58000000,
        )

    def test_shows_insider_filings(self):
        from analysis.models import SECFiling
        SECFiling.objects.create(
            ticker=self.ticker, form_type='4', filed_at=timezone.now(),
            filer_name='Tim Cook', filer_title='CEO',
            transaction_type='buy', shares=Decimal('10000'),
            price_per_share=Decimal('178.50'),
            total_value=Decimal('1785000'),
            accession_number='test_filing_1',
        )
        response = self.client.get(reverse('ticker_detail', args=['AAPL']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Insider Trading')
        self.assertContains(response, 'Tim Cook')
        self.assertContains(response, 'CEO')
        self.assertContains(response, 'Buy')

    def test_shows_no_filings_message(self):
        response = self.client.get(reverse('ticker_detail', args=['AAPL']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No recent insider transactions found')

    def test_shows_whale_signal_badge(self):
        from analysis.models import WhaleActivity
        WhaleActivity.objects.create(
            ticker=self.ticker, date=date.today(),
            signal='bullish', confidence=72,
            insider_buy_count=2,
        )
        response = self.client.get(reverse('ticker_detail', args=['AAPL']))
        self.assertContains(response, 'Bullish')
        self.assertContains(response, '72%')


class QuarterlyEarningGrowthPctTest(TestCase):
    def test_positive_growth(self):
        self.assertEqual(
            _compute_growth_pct(Decimal('1.50'), Decimal('1.00')),
            Decimal('50.00'),
        )

    def test_negative_growth(self):
        self.assertEqual(
            _compute_growth_pct(Decimal('0.80'), Decimal('1.00')),
            Decimal('-20.00'),
        )

    def test_prior_zero_returns_none(self):
        self.assertIsNone(_compute_growth_pct(Decimal('1.00'), Decimal('0')))

    def test_prior_negative_sign_preserved(self):
        # current improved from -0.50 to 0.50 -> +200%
        self.assertEqual(
            _compute_growth_pct(Decimal('0.50'), Decimal('-0.50')),
            Decimal('200.00'),
        )

    def test_none_inputs_return_none(self):
        self.assertIsNone(_compute_growth_pct(None, Decimal('1.00')))
        self.assertIsNone(_compute_growth_pct(Decimal('1.00'), None))


class QuarterlyEarningServiceTest(TestCase):
    def setUp(self):
        self.ticker = Ticker.objects.create(symbol='AAPL')

    @patch('market.services.yf.Ticker')
    def test_get_quarterly_earnings_computes_qoq(self, mock_yf):
        import pandas as pd
        idx = pd.to_datetime(['2025-03-31', '2025-06-30', '2025-09-30', '2025-12-31'])
        df = pd.DataFrame({'epsActual': [1.00, 1.50, 1.50, 1.95]}, index=idx)
        mock_stock = MagicMock()
        mock_stock.get_earnings_history.return_value = df
        mock_yf.return_value = mock_stock

        quarters = StockDataService.get_quarterly_earnings('AAPL')
        self.assertEqual(len(quarters), 4)
        self.assertIsNone(quarters[0]['growth_qoq_pct'])  # no prior
        # Q2 vs Q1: (1.5 - 1.0) / 1.0 * 100 = 50
        self.assertEqual(quarters[1]['growth_qoq_pct'], Decimal('50.00'))
        # Q3 vs Q2: flat -> 0
        self.assertEqual(quarters[2]['growth_qoq_pct'], Decimal('0.00'))
        # Q4 vs Q3: (1.95 - 1.5) / 1.5 * 100 = 30
        self.assertEqual(quarters[3]['growth_qoq_pct'], Decimal('30.00'))
        self.assertEqual(quarters[0]['fiscal_period'], '2025Q1')

    @patch('market.services.yf.Ticker')
    def test_get_quarterly_earnings_empty(self, mock_yf):
        import pandas as pd
        mock_stock = MagicMock()
        mock_stock.get_earnings_history.return_value = pd.DataFrame()
        mock_yf.return_value = mock_stock
        self.assertEqual(StockDataService.get_quarterly_earnings('AAPL'), [])

    @patch('market.services.yf.Ticker')
    def test_get_quarterly_earnings_handles_exception(self, mock_yf):
        mock_yf.side_effect = Exception('boom')
        self.assertEqual(StockDataService.get_quarterly_earnings('AAPL'), [])

    @patch('market.services.yf.Ticker')
    def test_refresh_quarterly_earnings_upserts_latest_four(self, mock_yf):
        import pandas as pd
        idx = pd.to_datetime(['2025-03-31', '2025-06-30', '2025-09-30', '2025-12-31'])
        df = pd.DataFrame({'epsActual': [1.00, 1.50, 1.50, 1.95]}, index=idx)
        mock_stock = MagicMock()
        mock_stock.get_earnings_history.return_value = df
        mock_yf.return_value = mock_stock

        saved = StockDataService.refresh_quarterly_earnings(self.ticker)
        self.assertEqual(saved, 4)
        rows = list(QuarterlyEarning.objects.filter(ticker=self.ticker).order_by('period_end_date'))
        self.assertEqual([r.fiscal_period for r in rows], ['2025Q1', '2025Q2', '2025Q3', '2025Q4'])
        self.assertIsNone(rows[0].growth_qoq_pct)
        self.assertEqual(rows[1].growth_qoq_pct, Decimal('50.00'))

        # Idempotent: running again with same data keeps count at 4
        StockDataService.refresh_quarterly_earnings(self.ticker)
        self.assertEqual(QuarterlyEarning.objects.filter(ticker=self.ticker).count(), 4)


class TickerDetailEarningsContextTest(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.ticker = Ticker.objects.create(
            symbol='AAPL', company_name='Apple Inc.',
            last_price=Decimal('178.50'), last_updated=timezone.now(),
        )

    def test_no_earnings_hides_card(self):
        response = self.client.get(reverse('ticker_detail', args=['AAPL']))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['has_earnings'])
        self.assertNotContains(response, 'Quarterly EPS Growth')

    def test_earnings_populated_context(self):
        for period_end, period, eps, growth in [
            (date(2025, 3, 31), '2025Q1', Decimal('1.00'), None),
            (date(2025, 6, 30), '2025Q2', Decimal('1.50'), Decimal('50.00')),
            (date(2025, 9, 30), '2025Q3', Decimal('1.50'), Decimal('0.00')),
            (date(2025, 12, 31), '2025Q4', Decimal('1.95'), Decimal('30.00')),
        ]:
            QuarterlyEarning.objects.create(
                ticker=self.ticker, period_end_date=period_end,
                fiscal_period=period, eps_actual=eps, growth_qoq_pct=growth,
            )
        response = self.client.get(reverse('ticker_detail', args=['AAPL']))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['has_earnings'])
        import json as _json
        labels = _json.loads(response.context['earnings_labels'])
        growth = _json.loads(response.context['earnings_growth_pct'])
        self.assertEqual(labels, ['2025Q1', '2025Q2', '2025Q3', '2025Q4'])
        self.assertEqual(growth, [None, 50.0, 0.0, 30.0])
        self.assertContains(response, 'Quarterly EPS Growth')
