from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from analysis.models import (
    AIAnalysis, CIKMapping, IndicatorSnapshot, OptionsSnapshot,
    PortfolioAnalysis, SECFiling, WhaleActivity,
)
from analysis.sec_service import SECFilingService
from analysis.services import AIAnalysisService, PortfolioAnalysisService, TechnicalIndicatorService, WhaleDetectionService
from market.models import NewsArticle, PriceHistory
from portfolio.models import Lot, Portfolio, Ticker, WatchlistItem


class LoggedInTestCase(TestCase):
    """Base test class that provides an authenticated client."""
    def setUp(self):
        self.user = User.objects.create_user('testuser', password='testpass')
        self.client = Client()
        self.client.force_login(self.user)


def _create_price_history(ticker, num_days=250, start_price=100.0):
    """Create synthetic price history for testing."""
    records = []
    price = start_price
    start_date = date(2024, 1, 1)
    for i in range(num_days):
        # Simple oscillating pattern
        import math
        wave = math.sin(i * 0.1) * 5
        price_today = start_price + wave + (i * 0.05)  # slight uptrend
        records.append(PriceHistory(
            ticker=ticker,
            date=start_date + timedelta(days=i),
            open=Decimal(str(round(price_today - 1, 2))),
            high=Decimal(str(round(price_today + 2, 2))),
            low=Decimal(str(round(price_today - 2, 2))),
            close=Decimal(str(round(price_today, 2))),
            volume=50000000,
        ))
    PriceHistory.objects.bulk_create(records)


class IndicatorSnapshotModelTest(TestCase):
    def test_str(self):
        ticker = Ticker.objects.create(symbol='TEST')
        snap = IndicatorSnapshot.objects.create(ticker=ticker, opportunity_score=75)
        self.assertEqual(str(snap), 'TEST score=75')

    def test_ordering(self):
        t1 = Ticker.objects.create(symbol='HIGH')
        t2 = Ticker.objects.create(symbol='LOW')
        IndicatorSnapshot.objects.create(ticker=t1, opportunity_score=90)
        IndicatorSnapshot.objects.create(ticker=t2, opportunity_score=30)
        results = list(IndicatorSnapshot.objects.all())
        self.assertEqual(results[0].ticker.symbol, 'HIGH')

    def test_one_to_one(self):
        ticker = Ticker.objects.create(symbol='TEST')
        IndicatorSnapshot.objects.create(ticker=ticker, opportunity_score=50)
        with self.assertRaises(Exception):
            IndicatorSnapshot.objects.create(ticker=ticker, opportunity_score=60)


class TechnicalIndicatorServiceTest(TestCase):
    def setUp(self):
        self.ticker = Ticker.objects.create(symbol='TEST', last_price=Decimal('110.00'))

    def test_not_enough_data(self):
        # Only 10 data points - should return None
        start = date(2024, 1, 1)
        for i in range(10):
            PriceHistory.objects.create(
                ticker=self.ticker,
                date=start + timedelta(days=i),
                open=Decimal('100'), high=Decimal('105'), low=Decimal('95'),
                close=Decimal('100'), volume=50000000,
            )
        result = TechnicalIndicatorService.compute_indicators(self.ticker)
        self.assertIsNone(result)

    def test_compute_indicators_basic(self):
        _create_price_history(self.ticker, num_days=250)
        snapshot = TechnicalIndicatorService.compute_indicators(self.ticker)
        self.assertIsNotNone(snapshot)
        self.assertIsInstance(snapshot, IndicatorSnapshot)
        self.assertEqual(snapshot.ticker, self.ticker)

        # All indicator values should be populated
        self.assertIsNotNone(snapshot.rsi)
        self.assertIsNotNone(snapshot.macd)
        self.assertIsNotNone(snapshot.macd_signal_line)
        self.assertIsNotNone(snapshot.macd_histogram)
        self.assertIsNotNone(snapshot.bb_upper)
        self.assertIsNotNone(snapshot.bb_middle)
        self.assertIsNotNone(snapshot.bb_lower)
        self.assertIsNotNone(snapshot.sma_50)
        self.assertIsNotNone(snapshot.sma_200)
        self.assertIsNotNone(snapshot.volume_ratio)

        # Score should be in range
        self.assertGreaterEqual(snapshot.opportunity_score, 0)
        self.assertLessEqual(snapshot.opportunity_score, 100)

    def test_signals_are_valid(self):
        _create_price_history(self.ticker, num_days=250)
        snapshot = TechnicalIndicatorService.compute_indicators(self.ticker)
        valid_signals = {'buy', 'hold', 'sell'}
        self.assertIn(snapshot.rsi_signal, valid_signals)
        self.assertIn(snapshot.macd_signal, valid_signals)
        self.assertIn(snapshot.bb_signal, valid_signals)
        self.assertIn(snapshot.sma_signal, valid_signals)
        self.assertIn(snapshot.volume_signal, valid_signals)
        self.assertIn(snapshot.sentiment_signal, valid_signals)

    def test_update_or_create(self):
        _create_price_history(self.ticker, num_days=250)
        snap1 = TechnicalIndicatorService.compute_indicators(self.ticker)
        snap2 = TechnicalIndicatorService.compute_indicators(self.ticker)
        # Should update, not create duplicate
        self.assertEqual(snap1.pk, snap2.pk)
        self.assertEqual(IndicatorSnapshot.objects.filter(ticker=self.ticker).count(), 1)

    def test_rsi_signal_logic(self):
        self.assertEqual(TechnicalIndicatorService._rsi_signal(25), 'buy')
        self.assertEqual(TechnicalIndicatorService._rsi_signal(50), 'hold')
        self.assertEqual(TechnicalIndicatorService._rsi_signal(75), 'sell')

    def test_bb_signal_logic(self):
        # Price near lower band
        self.assertEqual(TechnicalIndicatorService._bb_signal(101, 100, 120, 110), 'buy')
        # Price near upper band
        self.assertEqual(TechnicalIndicatorService._bb_signal(119, 100, 120, 110), 'sell')
        # Price in middle
        self.assertEqual(TechnicalIndicatorService._bb_signal(110, 100, 120, 110), 'hold')

    def test_sma_signal_logic(self):
        # Price above SMA50, golden cross
        self.assertEqual(TechnicalIndicatorService._sma_signal(110, 105, 100), 'buy')
        # Price below SMA50, death cross
        self.assertEqual(TechnicalIndicatorService._sma_signal(90, 95, 100), 'sell')
        # No SMA200
        self.assertEqual(TechnicalIndicatorService._sma_signal(110, 105, None), 'buy')

    def test_volume_signal_logic(self):
        self.assertEqual(TechnicalIndicatorService._volume_signal(2.0), 'buy')
        self.assertEqual(TechnicalIndicatorService._volume_signal(1.0), 'hold')
        self.assertEqual(TechnicalIndicatorService._volume_signal(0.3), 'sell')
        self.assertEqual(TechnicalIndicatorService._volume_signal(None), 'hold')

    def test_sentiment_signal_logic(self):
        self.assertEqual(TechnicalIndicatorService._sentiment_signal(0.3), 'buy')
        self.assertEqual(TechnicalIndicatorService._sentiment_signal(0.0), 'hold')
        self.assertEqual(TechnicalIndicatorService._sentiment_signal(-0.3), 'sell')
        self.assertEqual(TechnicalIndicatorService._sentiment_signal(None), 'hold')

    def test_score_with_sentiment(self):
        """Score should adjust weights when sentiment is available."""
        score_no_sent = TechnicalIndicatorService._compute_score(
            50, 0, 100, 95, 105, 100, 100, 100, 1.0, sentiment=None
        )
        score_pos_sent = TechnicalIndicatorService._compute_score(
            50, 0, 100, 95, 105, 100, 100, 100, 1.0, sentiment=0.8
        )
        score_neg_sent = TechnicalIndicatorService._compute_score(
            50, 0, 100, 95, 105, 100, 100, 100, 1.0, sentiment=-0.8
        )
        # Positive sentiment should increase score
        self.assertGreater(score_pos_sent, score_neg_sent)
        # All scores should be in range
        for s in (score_no_sent, score_pos_sent, score_neg_sent):
            self.assertGreaterEqual(s, 0)
            self.assertLessEqual(s, 100)

    def test_without_sma200_data(self):
        """With only 60 data points, SMA200 should be None but SMA50 populated."""
        _create_price_history(self.ticker, num_days=60)
        snapshot = TechnicalIndicatorService.compute_indicators(self.ticker)
        self.assertIsNotNone(snapshot)
        self.assertIsNotNone(snapshot.sma_50)
        self.assertIsNone(snapshot.sma_200)


class ChartDataOverlayTest(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.ticker = Ticker.objects.create(symbol='TEST')
        _create_price_history(self.ticker, num_days=250)

    def test_chart_data_with_sma_overlay(self):
        response = self.client.get(
            reverse('chart_data', args=['TEST']),
            {'period': '1y', 'indicators': 'sma50'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('sma50', data)
        self.assertEqual(len(data['sma50']), len(data['prices']))

    def test_chart_data_with_bb_overlay(self):
        response = self.client.get(
            reverse('chart_data', args=['TEST']),
            {'period': '1y', 'indicators': 'bb'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('bb_upper', data)
        self.assertIn('bb_lower', data)

    def test_chart_data_without_indicators(self):
        response = self.client.get(
            reverse('chart_data', args=['TEST']),
            {'period': '1y'}
        )
        data = response.json()
        self.assertNotIn('sma50', data)
        self.assertNotIn('bb_upper', data)


class TickerDetailWithIndicatorsTest(LoggedInTestCase):
    def test_detail_shows_indicators(self):
        ticker = Ticker.objects.create(
            symbol='TEST', company_name='Test Inc.',
            last_price=Decimal('110.00'), last_updated=timezone.now(),
        )
        _create_price_history(ticker, num_days=250)
        TechnicalIndicatorService.compute_indicators(ticker)

        response = self.client.get(reverse('ticker_detail', args=['TEST']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Technical Indicators')
        self.assertContains(response, 'RSI')
        self.assertContains(response, 'MACD')
        self.assertContains(response, 'Score:')

    def test_detail_without_indicators(self):
        ticker = Ticker.objects.create(
            symbol='EMPTY', company_name='Empty Inc.',
            last_price=Decimal('50.00'), last_updated=timezone.now(),
        )
        response = self.client.get(reverse('ticker_detail', args=['EMPTY']))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'RSI (14)')
        self.assertNotContains(response, 'Score:')


class OpportunitiesViewTest(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.t1 = Ticker.objects.create(symbol='HIGH', company_name='High Corp', sector='Tech',
                                         last_price=Decimal('100'), day_change_pct=Decimal('2.5'))
        self.t2 = Ticker.objects.create(symbol='LOW', company_name='Low Corp', sector='Finance',
                                         last_price=Decimal('50'), day_change_pct=Decimal('-1.0'))
        IndicatorSnapshot.objects.create(ticker=self.t1, opportunity_score=85,
                                          rsi_signal='buy', macd_signal='buy',
                                          bb_signal='hold', sma_signal='buy',
                                          volume_signal='hold', sentiment_signal='buy')
        IndicatorSnapshot.objects.create(ticker=self.t2, opportunity_score=30,
                                          rsi_signal='sell', macd_signal='sell',
                                          bb_signal='hold', sma_signal='sell',
                                          volume_signal='hold', sentiment_signal='hold')
        # Link tickers to user via portfolio so they appear in opportunities
        portfolio = Portfolio.objects.create(name='Test', user=self.user)
        Lot.objects.create(portfolio=portfolio, ticker=self.t1, shares=Decimal('1'),
                           cost_basis=Decimal('100'), purchase_date=date(2024, 1, 1))
        Lot.objects.create(portfolio=portfolio, ticker=self.t2, shares=Decimal('1'),
                           cost_basis=Decimal('50'), purchase_date=date(2024, 1, 1))

    def test_page_loads(self):
        response = self.client.get(reverse('opportunities'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Buying Opportunities')
        self.assertContains(response, 'HIGH')
        self.assertContains(response, 'LOW')

    def test_score_ordering(self):
        response = self.client.get(reverse('opportunities'))
        content = response.content.decode()
        # HIGH (score 85) should appear before LOW (score 30)
        self.assertLess(content.index('HIGH'), content.index('LOW'))

    def test_signal_filter(self):
        response = self.client.get(reverse('opportunities'), {'signal': 'buy'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'HIGH')
        self.assertNotContains(response, 'LOW')

    def test_sector_filter(self):
        response = self.client.get(reverse('opportunities'), {'sector': 'Finance'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'LOW')
        self.assertNotContains(response, 'HIGH')

    def test_sort_by_name(self):
        response = self.client.get(reverse('opportunities'), {'sort': 'name'})
        content = response.content.decode()
        self.assertLess(content.index('HIGH'), content.index('LOW'))

    def test_summary_stats(self):
        response = self.client.get(reverse('opportunities'))
        self.assertContains(response, '2')  # total
        self.assertContains(response, '1')  # buy_count or sell_count


class RadarDataViewTest(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.ticker = Ticker.objects.create(symbol='TEST', last_price=Decimal('100'))
        IndicatorSnapshot.objects.create(
            ticker=self.ticker, opportunity_score=65,
            rsi=Decimal('45.00'), macd_histogram=Decimal('0.5000'),
            bb_upper=Decimal('110'), bb_lower=Decimal('90'), bb_middle=Decimal('100'),
            sma_50=Decimal('95'), sma_200=Decimal('90'),
            volume_ratio=Decimal('1.20'), sentiment_score=Decimal('0.200'),
        )

    def test_radar_data_returns_json(self):
        response = self.client.get(reverse('radar_data', args=['TEST']))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('labels', data)
        self.assertIn('scores', data)
        self.assertEqual(len(data['labels']), 6)  # RSI, MACD, BB, SMA, Vol, Sentiment
        self.assertEqual(len(data['scores']), 6)
        self.assertIn('overall', data)
        self.assertEqual(data['overall'], 65)

    def test_radar_data_404(self):
        response = self.client.get(reverse('radar_data', args=['ZZZZ']))
        self.assertEqual(response.status_code, 404)

    def test_radar_data_no_indicators(self):
        t2 = Ticker.objects.create(symbol='EMPTY')
        response = self.client.get(reverse('radar_data', args=['EMPTY']))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['labels'], [])


class WatchlistViewTest(LoggedInTestCase):

    def test_watchlist_page_loads(self):
        response = self.client.get(reverse('watchlist'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Watchlist')

    def test_add_to_watchlist(self):
        response = self.client.post(reverse('watchlist_add'), {'symbol': 'AAPL'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Ticker.objects.filter(symbol='AAPL').exists())
        from portfolio.models import WatchlistItem
        self.assertEqual(WatchlistItem.objects.count(), 1)

    def test_add_duplicate(self):
        ticker = Ticker.objects.create(symbol='AAPL')
        from portfolio.models import WatchlistItem
        WatchlistItem.objects.create(ticker=ticker, user=self.user)
        response = self.client.post(reverse('watchlist_add'), {'symbol': 'AAPL'})
        self.assertEqual(response.status_code, 400)

    def test_remove_from_watchlist(self):
        ticker = Ticker.objects.create(symbol='AAPL')
        from portfolio.models import WatchlistItem
        item = WatchlistItem.objects.create(ticker=ticker, user=self.user)
        response = self.client.post(reverse('watchlist_remove', args=[item.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WatchlistItem.objects.count(), 0)

    def test_remove_requires_post(self):
        ticker = Ticker.objects.create(symbol='AAPL')
        from portfolio.models import WatchlistItem
        item = WatchlistItem.objects.create(ticker=ticker, user=self.user)
        response = self.client.get(reverse('watchlist_remove', args=[item.pk]))
        self.assertEqual(response.status_code, 405)

    def test_watchlist_shows_items(self):
        ticker = Ticker.objects.create(symbol='AAPL', company_name='Apple Inc.',
                                        last_price=Decimal('178.50'))
        from portfolio.models import WatchlistItem
        WatchlistItem.objects.create(ticker=ticker, user=self.user, notes='Watching for dip')
        response = self.client.get(reverse('watchlist'))
        self.assertContains(response, 'AAPL')
        self.assertContains(response, 'Watching for dip')


class CompareViewTest(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.t1 = Ticker.objects.create(symbol='AAPL', company_name='Apple',
                                         last_price=Decimal('178.50'))
        self.t2 = Ticker.objects.create(symbol='MSFT', company_name='Microsoft',
                                         last_price=Decimal('380.00'))
        IndicatorSnapshot.objects.create(ticker=self.t1, opportunity_score=72)
        IndicatorSnapshot.objects.create(ticker=self.t2, opportunity_score=65)

    def test_compare_page_loads(self):
        response = self.client.get(reverse('compare'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Compare Tickers')

    def test_compare_with_symbols(self):
        response = self.client.get(reverse('compare'), {'symbols': 'AAPL,MSFT'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Apple')
        self.assertContains(response, 'Microsoft')
        self.assertContains(response, '72')  # AAPL score
        self.assertContains(response, '65')  # MSFT score

    def test_compare_invalid_symbol(self):
        response = self.client.get(reverse('compare'), {'symbols': 'ZZZZ'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No matching tickers')

    def test_compare_empty(self):
        response = self.client.get(reverse('compare'), {'symbols': ''})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Enter 2-3 ticker symbols')


class SignalSummaryTest(TestCase):
    def test_signal_summary_property(self):
        ticker = Ticker.objects.create(symbol='TEST')
        snap = IndicatorSnapshot.objects.create(
            ticker=ticker, opportunity_score=50,
            rsi_signal='buy', macd_signal='sell',
            bb_signal='hold', sma_signal='buy',
            volume_signal='hold', sentiment_signal='buy',
        )
        summary = snap.signal_summary
        self.assertEqual(len(summary), 6)
        self.assertEqual(summary[0], ('RSI', 'buy'))
        self.assertEqual(summary[1], ('MACD', 'sell'))


# ---- AI Analysis Tests ----

class AIAnalysisModelTest(TestCase):
    def test_create_and_str(self):
        ticker = Ticker.objects.create(symbol='TEST')
        analysis = AIAnalysis.objects.create(
            ticker=ticker, analysis_text='Test analysis.', model_name='llama3.2:1b'
        )
        self.assertIn('TEST', str(analysis))
        self.assertIn('AI analysis', str(analysis))

    def test_one_to_one(self):
        ticker = Ticker.objects.create(symbol='TEST')
        AIAnalysis.objects.create(ticker=ticker, analysis_text='First.')
        with self.assertRaises(Exception):
            AIAnalysis.objects.create(ticker=ticker, analysis_text='Second.')

    def test_related_name(self):
        ticker = Ticker.objects.create(symbol='TEST')
        AIAnalysis.objects.create(ticker=ticker, analysis_text='Via related.')
        self.assertEqual(ticker.ai_analysis.analysis_text, 'Via related.')


class AIAnalysisServiceBuildPromptTest(TestCase):
    def setUp(self):
        self.ticker = Ticker.objects.create(
            symbol='AAPL', company_name='Apple Inc.',
            last_price=Decimal('178.50'), day_change_pct=Decimal('1.5'),
            sector='Technology', pe_ratio=Decimal('28.5'),
            market_cap=Decimal('2800000000000'),
            week_52_high=Decimal('199.62'), week_52_low=Decimal('124.17'),
        )
        self.indicators = IndicatorSnapshot.objects.create(
            ticker=self.ticker, opportunity_score=72,
            rsi=Decimal('45.00'), rsi_signal='hold',
            macd_histogram=Decimal('0.5000'), macd_signal='buy',
            bb_signal='hold', sma_signal='buy',
            sma_50=Decimal('170.00'), sma_200=Decimal('160.00'),
            volume_ratio=Decimal('1.20'), volume_signal='hold',
            sentiment_score=Decimal('0.200'), sentiment_signal='buy',
        )

    def test_prompt_includes_ticker_data(self):
        prompt = AIAnalysisService._build_prompt(self.ticker, self.indicators, [])
        self.assertIn('AAPL', prompt)
        self.assertIn('Apple Inc.', prompt)
        self.assertIn('178.5', prompt)
        self.assertIn('Technology', prompt)

    def test_prompt_includes_indicators(self):
        prompt = AIAnalysisService._build_prompt(self.ticker, self.indicators, [])
        self.assertIn('RSI(14)', prompt)
        self.assertIn('72/100', prompt)
        self.assertIn('buy', prompt)

    def test_prompt_includes_news(self):
        article = NewsArticle.objects.create(
            ticker=self.ticker, title='Apple beats earnings expectations',
            url='https://example.com/1', source='Test',
            sentiment_label='positive', published_at=timezone.now(),
        )
        prompt = AIAnalysisService._build_prompt(self.ticker, self.indicators, [article])
        self.assertIn('Apple beats earnings', prompt)
        self.assertIn('[positive]', prompt)

    def test_prompt_without_indicators(self):
        prompt = AIAnalysisService._build_prompt(self.ticker, None, [])
        self.assertIn('AAPL', prompt)
        self.assertNotIn('RSI(14)', prompt)


class AIAnalysisServiceGenerateTest(TestCase):
    def setUp(self):
        self.ticker = Ticker.objects.create(
            symbol='AAPL', company_name='Apple Inc.',
            last_price=Decimal('178.50'), day_change_pct=Decimal('1.5'),
        )

    @patch('analysis.services.ollama')
    def test_generate_creates_analysis(self, mock_ollama_module):
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            'message': {'content': 'AAPL shows bullish momentum with strong technicals.'}
        }
        mock_ollama_module.Client.return_value = mock_client

        result = AIAnalysisService.generate_analysis(self.ticker)
        self.assertIsNotNone(result)
        self.assertEqual(result.ticker, self.ticker)
        self.assertIn('bullish momentum', result.analysis_text)
        self.assertEqual(AIAnalysis.objects.count(), 1)

    @patch('analysis.services.ollama')
    def test_prompt_hash_skips_unchanged(self, mock_ollama_module):
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            'message': {'content': 'Analysis text.'}
        }
        mock_ollama_module.Client.return_value = mock_client

        # First call generates
        result1 = AIAnalysisService.generate_analysis(self.ticker)
        self.assertEqual(mock_client.chat.call_count, 1)

        # Second call with same data should skip
        result2 = AIAnalysisService.generate_analysis(self.ticker)
        self.assertEqual(mock_client.chat.call_count, 1)  # not called again
        self.assertEqual(result1.pk, result2.pk)

    @patch('analysis.services.ollama')
    def test_force_regenerates(self, mock_ollama_module):
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            'message': {'content': 'Analysis text.'}
        }
        mock_ollama_module.Client.return_value = mock_client

        AIAnalysisService.generate_analysis(self.ticker)
        AIAnalysisService.generate_analysis(self.ticker, force=True)
        self.assertEqual(mock_client.chat.call_count, 2)

    @patch('analysis.services.ollama')
    def test_connection_error_returns_none(self, mock_ollama_module):
        mock_ollama_module.Client.side_effect = ConnectionError("refused")
        result = AIAnalysisService.generate_analysis(self.ticker)
        self.assertIsNone(result)
        self.assertEqual(AIAnalysis.objects.count(), 0)

    @patch('analysis.services.ollama')
    def test_update_or_create_on_regenerate(self, mock_ollama_module):
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            'message': {'content': 'Updated analysis.'}
        }
        mock_ollama_module.Client.return_value = mock_client

        # Pre-create an analysis
        AIAnalysis.objects.create(
            ticker=self.ticker, analysis_text='Old.', prompt_hash='old_hash'
        )
        result = AIAnalysisService.generate_analysis(self.ticker)
        self.assertEqual(AIAnalysis.objects.count(), 1)
        self.assertEqual(result.analysis_text, 'Updated analysis.')


class TickerDetailAIAnalysisTest(LoggedInTestCase):
    def test_detail_shows_existing_analysis(self):
        ticker = Ticker.objects.create(
            symbol='TEST', company_name='Test Inc.',
            last_price=Decimal('100.00'), last_updated=timezone.now(),
        )
        AIAnalysis.objects.create(
            ticker=ticker, analysis_text='Test AI analysis content here.',
        )
        response = self.client.get(reverse('ticker_detail', args=['TEST']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kevin's Take")
        self.assertContains(response, 'Test AI analysis content here.')

    def test_detail_without_analysis_shows_ask_button(self):
        ticker = Ticker.objects.create(
            symbol='NOAI', company_name='No AI Inc.',
            last_price=Decimal('50.00'), last_updated=timezone.now(),
        )
        response = self.client.get(reverse('ticker_detail', args=['NOAI']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ask Kevin What He Thinks')
        self.assertNotContains(response, "Kevin's Take")

    @patch('analysis.services.ollama')
    def test_generate_endpoint(self, mock_ollama_module):
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            'message': {'content': 'Kevin says this stock looks interesting.'}
        }
        mock_ollama_module.Client.return_value = mock_client

        ticker = Ticker.objects.create(
            symbol='TEST', company_name='Test Inc.',
            last_price=Decimal('100.00'), last_updated=timezone.now(),
        )
        response = self.client.post(reverse('generate_ai_analysis', args=['TEST']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kevin's Take")
        self.assertContains(response, 'Kevin says this stock looks interesting.')
        self.assertEqual(AIAnalysis.objects.count(), 1)

    def test_generate_endpoint_requires_post(self):
        Ticker.objects.create(symbol='TEST', last_price=Decimal('100.00'))
        response = self.client.get(reverse('generate_ai_analysis', args=['TEST']))
        self.assertEqual(response.status_code, 405)


class OptionsSnapshotModelTest(TestCase):
    def test_str(self):
        ticker = Ticker.objects.create(symbol='TEST')
        snap = OptionsSnapshot.objects.create(ticker=ticker, options_score=72)
        self.assertEqual(str(snap), 'TEST options score=72')

    def test_one_to_one(self):
        ticker = Ticker.objects.create(symbol='TEST')
        OptionsSnapshot.objects.create(ticker=ticker, options_score=50)
        with self.assertRaises(Exception):
            OptionsSnapshot.objects.create(ticker=ticker, options_score=60)

    def test_defaults(self):
        ticker = Ticker.objects.create(symbol='TEST')
        snap = OptionsSnapshot.objects.create(ticker=ticker)
        self.assertEqual(snap.options_score, 50)
        self.assertEqual(snap.options_signal, 'hold')
        self.assertFalse(snap.has_unusual_activity)


class OptionsInCompositeScoreTest(TestCase):
    def setUp(self):
        self.ticker = Ticker.objects.create(symbol='TEST', last_price=Decimal('110.00'))
        _create_price_history(self.ticker, num_days=250)

    @patch('market.services.NewsService.get_aggregate_sentiment', return_value=Decimal('0.1'))
    def test_score_with_options(self, mock_sentiment):
        # Create an options snapshot with a high score
        OptionsSnapshot.objects.create(
            ticker=self.ticker, options_score=90, options_signal='buy'
        )
        snapshot = TechnicalIndicatorService.compute_indicators(self.ticker)
        self.assertIsNotNone(snapshot)
        score_with_options = snapshot.opportunity_score

        # Remove options and recompute
        OptionsSnapshot.objects.filter(ticker=self.ticker).delete()
        snapshot2 = TechnicalIndicatorService.compute_indicators(self.ticker)
        score_without_options = snapshot2.opportunity_score

        # With a high options score (90), composite should be higher
        self.assertGreaterEqual(score_with_options, score_without_options)

    @patch('market.services.NewsService.get_aggregate_sentiment', return_value=None)
    def test_score_without_sentiment_with_options(self, mock_sentiment):
        OptionsSnapshot.objects.create(
            ticker=self.ticker, options_score=80, options_signal='buy'
        )
        snapshot = TechnicalIndicatorService.compute_indicators(self.ticker)
        self.assertIsNotNone(snapshot)
        self.assertGreaterEqual(snapshot.opportunity_score, 0)
        self.assertLessEqual(snapshot.opportunity_score, 100)

    @patch('market.services.NewsService.get_aggregate_sentiment', return_value=Decimal('0.1'))
    def test_signal_summary_includes_options(self, mock_sentiment):
        OptionsSnapshot.objects.create(
            ticker=self.ticker, options_score=80, options_signal='buy'
        )
        snapshot = TechnicalIndicatorService.compute_indicators(self.ticker)
        signals = snapshot.signal_summary
        signal_labels = [label for label, _ in signals]
        self.assertIn('Opt', signal_labels)

    @patch('market.services.NewsService.get_aggregate_sentiment', return_value=Decimal('0.1'))
    def test_signal_summary_without_options(self, mock_sentiment):
        snapshot = TechnicalIndicatorService.compute_indicators(self.ticker)
        signals = snapshot.signal_summary
        signal_labels = [label for label, _ in signals]
        self.assertNotIn('Opt', signal_labels)


class OptionsRadarChartTest(LoggedInTestCase):
    def test_radar_includes_options(self):
        ticker = Ticker.objects.create(
            symbol='TEST', last_price=Decimal('100.00'), last_updated=timezone.now()
        )
        IndicatorSnapshot.objects.create(
            ticker=ticker, rsi=Decimal('45'), opportunity_score=55
        )
        OptionsSnapshot.objects.create(
            ticker=ticker, options_score=75, options_signal='buy'
        )
        response = self.client.get(reverse('radar_data', args=['TEST']))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('Options', data['labels'])
        idx = data['labels'].index('Options')
        self.assertEqual(data['scores'][idx], 75.0)

    def test_radar_without_options(self):
        ticker = Ticker.objects.create(
            symbol='TEST', last_price=Decimal('100.00'), last_updated=timezone.now()
        )
        IndicatorSnapshot.objects.create(
            ticker=ticker, rsi=Decimal('45'), opportunity_score=55
        )
        response = self.client.get(reverse('radar_data', args=['TEST']))
        data = response.json()
        self.assertNotIn('Options', data['labels'])


class PriceTargetCalculationTest(TestCase):
    def test_basic_targets(self):
        buy, sell = TechnicalIndicatorService._compute_price_targets(
            price=100.0,
            bb_lower=90.0, bb_upper=110.0,
            sma_50=105.0, sma_200=95.0,
            week_52_high=Decimal('120.00'), week_52_low=Decimal('80.00'),
            max_pain=98.0,
        )
        self.assertIsNotNone(buy)
        self.assertIsNotNone(sell)
        self.assertLess(buy, 100.0)
        self.assertGreater(sell, 100.0)

    def test_targets_with_none_price(self):
        buy, sell = TechnicalIndicatorService._compute_price_targets(
            price=None,
            bb_lower=90.0, bb_upper=110.0,
            sma_50=105.0, sma_200=95.0,
            week_52_high=None, week_52_low=None,
        )
        self.assertIsNone(buy)
        self.assertIsNone(sell)

    def test_max_pain_above_price_goes_to_sell(self):
        buy, sell = TechnicalIndicatorService._compute_price_targets(
            price=100.0,
            bb_lower=90.0, bb_upper=110.0,
            sma_50=95.0, sma_200=92.0,
            week_52_high=Decimal('120.00'), week_52_low=Decimal('80.00'),
            max_pain=108.0,  # above current price
        )
        self.assertGreater(sell, 100.0)

    def test_max_pain_below_price_goes_to_buy(self):
        buy, sell = TechnicalIndicatorService._compute_price_targets(
            price=100.0,
            bb_lower=90.0, bb_upper=110.0,
            sma_50=105.0, sma_200=95.0,
            week_52_high=Decimal('120.00'), week_52_low=Decimal('80.00'),
            max_pain=92.0,  # below current price
        )
        self.assertLess(buy, 100.0)

    def test_buy_target_clamped_below_price(self):
        # All support levels above price should clamp buy target to 95% of price
        buy, sell = TechnicalIndicatorService._compute_price_targets(
            price=50.0,
            bb_lower=55.0, bb_upper=70.0,
            sma_50=60.0, sma_200=58.0,
            week_52_high=Decimal('75.00'), week_52_low=Decimal('52.00'),
        )
        self.assertLessEqual(buy, 50.0)

    def test_sell_target_clamped_above_price(self):
        # All resistance levels below price should clamp sell target to 105% of price
        buy, sell = TechnicalIndicatorService._compute_price_targets(
            price=100.0,
            bb_lower=70.0, bb_upper=90.0,
            sma_50=85.0, sma_200=80.0,
            week_52_high=Decimal('95.00'), week_52_low=Decimal('60.00'),
        )
        self.assertGreaterEqual(sell, 100.0)

    def test_no_optional_data(self):
        buy, sell = TechnicalIndicatorService._compute_price_targets(
            price=100.0,
            bb_lower=90.0, bb_upper=110.0,
            sma_50=None, sma_200=None,
            week_52_high=None, week_52_low=None,
        )
        self.assertIsNotNone(buy)
        self.assertIsNotNone(sell)
        self.assertAlmostEqual(buy, 90.0, places=0)
        self.assertAlmostEqual(sell, 110.0, places=0)


class PriceTargetInComputeIndicatorsTest(TestCase):
    def setUp(self):
        self.ticker = Ticker.objects.create(
            symbol='TEST', last_price=Decimal('110.00'),
            week_52_high=Decimal('130.00'), week_52_low=Decimal('80.00'),
        )
        _create_price_history(self.ticker, num_days=250)

    @patch('market.services.NewsService.get_aggregate_sentiment', return_value=Decimal('0.1'))
    def test_indicators_include_price_targets(self, mock_sentiment):
        snapshot = TechnicalIndicatorService.compute_indicators(self.ticker)
        self.assertIsNotNone(snapshot)
        self.assertIsNotNone(snapshot.buy_target)
        self.assertIsNotNone(snapshot.sell_target)
        self.assertLess(snapshot.buy_target, self.ticker.last_price)
        self.assertGreater(snapshot.sell_target, self.ticker.last_price)

    @patch('market.services.NewsService.get_aggregate_sentiment', return_value=Decimal('0.1'))
    def test_price_targets_with_options_max_pain(self, mock_sentiment):
        OptionsSnapshot.objects.create(
            ticker=self.ticker, options_score=70, options_signal='buy',
            max_pain=Decimal('105.00'),
        )
        snapshot = TechnicalIndicatorService.compute_indicators(self.ticker)
        self.assertIsNotNone(snapshot.buy_target)
        self.assertIsNotNone(snapshot.sell_target)


class PortfolioAnalysisModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', password='testpass')

    def test_str(self):
        portfolio = Portfolio.objects.create(name='Test Portfolio', user=self.user)
        analysis = PortfolioAnalysis.objects.create(
            portfolio=portfolio,
            top_picks_text='Pick 1...',
            portfolio_analysis_text='Overall...',
        )
        self.assertIn('Test Portfolio', str(analysis))

    def test_one_to_one(self):
        portfolio = Portfolio.objects.create(name='Test Portfolio', user=self.user)
        PortfolioAnalysis.objects.create(portfolio=portfolio)
        with self.assertRaises(Exception):
            PortfolioAnalysis.objects.create(portfolio=portfolio)


class PortfolioAnalysisServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', password='testpass')
        self.portfolio = Portfolio.objects.create(name='Test Portfolio', user=self.user)
        self.ticker1 = Ticker.objects.create(
            symbol='AAPL', company_name='Apple Inc.',
            last_price=Decimal('180.00'), sector='Technology',
            week_52_high=Decimal('200.00'), week_52_low=Decimal('140.00'),
        )
        self.ticker2 = Ticker.objects.create(
            symbol='MSFT', company_name='Microsoft',
            last_price=Decimal('350.00'), sector='Technology',
            week_52_high=Decimal('400.00'), week_52_low=Decimal('280.00'),
        )
        self.ticker3 = Ticker.objects.create(
            symbol='JPM', company_name='JPMorgan',
            last_price=Decimal('170.00'), sector='Financials',
            week_52_high=Decimal('200.00'), week_52_low=Decimal('130.00'),
        )
        # Add lots to portfolio
        Lot.objects.create(
            portfolio=self.portfolio, ticker=self.ticker1,
            shares=Decimal('10'), cost_basis=Decimal('150.00'),
            purchase_date=date(2024, 1, 1),
        )
        Lot.objects.create(
            portfolio=self.portfolio, ticker=self.ticker2,
            shares=Decimal('5'), cost_basis=Decimal('300.00'),
            purchase_date=date(2024, 1, 1),
        )
        # Add ticker3 to watchlist only
        WatchlistItem.objects.create(ticker=self.ticker3, user=self.user)

        # Create indicator snapshots
        IndicatorSnapshot.objects.create(ticker=self.ticker1, opportunity_score=80)
        IndicatorSnapshot.objects.create(ticker=self.ticker2, opportunity_score=60)
        IndicatorSnapshot.objects.create(ticker=self.ticker3, opportunity_score=90)

    def test_gather_candidates_includes_portfolio_and_watchlist(self):
        candidates = PortfolioAnalysisService._gather_candidates(self.portfolio)
        symbols = {c['ticker'].symbol for c in candidates}
        self.assertIn('AAPL', symbols)
        self.assertIn('MSFT', symbols)
        self.assertIn('JPM', symbols)

    def test_gather_candidates_flags_source(self):
        candidates = PortfolioAnalysisService._gather_candidates(self.portfolio)
        by_symbol = {c['ticker'].symbol: c for c in candidates}
        self.assertTrue(by_symbol['AAPL']['in_portfolio'])
        self.assertFalse(by_symbol['AAPL']['in_watchlist'])
        self.assertFalse(by_symbol['JPM']['in_portfolio'])
        self.assertTrue(by_symbol['JPM']['in_watchlist'])

    def test_pick_top_2(self):
        candidates = PortfolioAnalysisService._gather_candidates(self.portfolio)
        top = PortfolioAnalysisService._pick_top_2(candidates)
        self.assertEqual(len(top), 2)
        # Top 2 should be JPM (90) and AAPL (80)
        symbols = [c['ticker'].symbol for c in top]
        self.assertEqual(symbols[0], 'JPM')
        self.assertEqual(symbols[1], 'AAPL')

    def test_build_ticker_summary(self):
        candidates = PortfolioAnalysisService._gather_candidates(self.portfolio)
        aapl = next(c for c in candidates if c['ticker'].symbol == 'AAPL')
        summary = PortfolioAnalysisService._build_ticker_summary(aapl)
        self.assertIn('AAPL', summary)
        self.assertIn('Apple', summary)
        self.assertIn('Opportunity score: 80', summary)
        self.assertIn('in portfolio', summary)

    def test_build_top_picks_prompt(self):
        candidates = PortfolioAnalysisService._gather_candidates(self.portfolio)
        top = PortfolioAnalysisService._pick_top_2(candidates)
        prompt = PortfolioAnalysisService._build_top_picks_prompt(top, self.portfolio)
        self.assertIn('PICK #1', prompt)
        self.assertIn('PICK #2', prompt)
        self.assertIn('Test Portfolio', prompt)

    def test_build_portfolio_analysis_prompt(self):
        candidates = PortfolioAnalysisService._gather_candidates(self.portfolio)
        holdings = self.portfolio.get_holdings()
        prompt = PortfolioAnalysisService._build_portfolio_analysis_prompt(
            candidates, self.portfolio, holdings
        )
        self.assertIn('Test Portfolio', prompt)
        self.assertIn('AAPL', prompt)
        self.assertIn('MSFT', prompt)
        self.assertIn('Watchlist', prompt)
        self.assertIn('JPM', prompt)

    @patch('analysis.services.ollama')
    def test_generate_analysis(self, mock_ollama_module):
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            'message': {'content': 'Test analysis output.'}
        }
        mock_ollama_module.Client.return_value = mock_client

        result = PortfolioAnalysisService.generate_analysis(self.portfolio, force=True)
        self.assertIsNotNone(result)
        self.assertEqual(PortfolioAnalysis.objects.count(), 1)
        self.assertIn('JPM', result.top_pick_symbols)
        self.assertIn('AAPL', result.top_pick_symbols)
        # Two LLM calls: picks + portfolio analysis
        self.assertEqual(mock_client.chat.call_count, 2)

    @patch('analysis.services.ollama')
    def test_generate_skips_unchanged(self, mock_ollama_module):
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            'message': {'content': 'Analysis.'}
        }
        mock_ollama_module.Client.return_value = mock_client

        # First call
        result1 = PortfolioAnalysisService.generate_analysis(self.portfolio, force=True)
        # Second call without force — should skip
        result2 = PortfolioAnalysisService.generate_analysis(self.portfolio, force=False)
        self.assertEqual(result1.pk, result2.pk)
        # Only 2 LLM calls (from first invocation)
        self.assertEqual(mock_client.chat.call_count, 2)

    @patch('analysis.services.ollama')
    def test_connection_error_returns_none(self, mock_ollama_module):
        mock_ollama_module.Client.side_effect = ConnectionError("refused")
        result = PortfolioAnalysisService.generate_analysis(self.portfolio, force=True)
        self.assertIsNone(result)


class PortfolioAnalysisViewTest(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.portfolio = Portfolio.objects.create(name='View Test', user=self.user)
        self.ticker = Ticker.objects.create(
            symbol='TEST', last_price=Decimal('100.00'),
        )
        Lot.objects.create(
            portfolio=self.portfolio, ticker=self.ticker,
            shares=Decimal('10'), cost_basis=Decimal('90.00'),
            purchase_date=date(2024, 6, 1),
        )
        IndicatorSnapshot.objects.create(ticker=self.ticker, opportunity_score=75)

    def test_portfolio_detail_shows_analyze_button(self):
        response = self.client.get(reverse('portfolio_detail', args=[self.portfolio.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ask Kevin to Analyze Portfolio')

    def test_portfolio_detail_shows_existing_analysis(self):
        PortfolioAnalysis.objects.create(
            portfolio=self.portfolio,
            top_picks_text='TEST is a strong pick because...',
            top_pick_symbols=['TEST'],
            portfolio_analysis_text='Overall the portfolio looks healthy.',
        )
        response = self.client.get(reverse('portfolio_detail', args=[self.portfolio.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Top Picks to Add To')
        self.assertContains(response, 'TEST is a strong pick because')
        self.assertContains(response, 'Portfolio Analysis')
        self.assertContains(response, 'Overall the portfolio looks healthy')

    @patch('analysis.services.ollama')
    def test_generate_endpoint(self, mock_ollama_module):
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            'message': {'content': 'Kevin says portfolio looks great.'}
        }
        mock_ollama_module.Client.return_value = mock_client

        response = self.client.post(
            reverse('generate_portfolio_analysis', args=[self.portfolio.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PortfolioAnalysis.objects.count(), 1)

    def test_generate_endpoint_requires_post(self):
        response = self.client.get(
            reverse('generate_portfolio_analysis', args=[self.portfolio.pk])
        )
        self.assertEqual(response.status_code, 405)


# ── Whale Activity Tests ──────────────────────────────────────────────────────


class CIKMappingModelTest(TestCase):
    def setUp(self):
        self.ticker = Ticker.objects.create(symbol='AAPL')

    def test_str(self):
        mapping = CIKMapping.objects.create(ticker=self.ticker, cik='0000320193')
        self.assertIn('AAPL', str(mapping))
        self.assertIn('0000320193', str(mapping))

    def test_one_to_one(self):
        CIKMapping.objects.create(ticker=self.ticker, cik='0000320193')
        with self.assertRaises(Exception):
            CIKMapping.objects.create(ticker=self.ticker, cik='9999999999')


class SECFilingModelTest(TestCase):
    def setUp(self):
        self.ticker = Ticker.objects.create(symbol='AAPL')

    def test_str(self):
        filing = SECFiling.objects.create(
            ticker=self.ticker, form_type='4', filed_at=timezone.now(),
            filer_name='Tim Cook', transaction_type='buy',
            accession_number='0001234567890001',
        )
        self.assertIn('AAPL', str(filing))
        self.assertIn('Tim Cook', str(filing))

    def test_unique_together(self):
        SECFiling.objects.create(
            ticker=self.ticker, form_type='4', filed_at=timezone.now(),
            filer_name='Tim Cook', transaction_type='buy',
            accession_number='0001234567890001',
        )
        with self.assertRaises(Exception):
            SECFiling.objects.create(
                ticker=self.ticker, form_type='4', filed_at=timezone.now(),
                filer_name='Luca Maestri', transaction_type='sell',
                accession_number='0001234567890001',
            )

    def test_ordering(self):
        f1 = SECFiling.objects.create(
            ticker=self.ticker, form_type='4', filed_at=timezone.now() - timedelta(days=5),
            filer_name='A', transaction_type='buy', accession_number='a1',
        )
        f2 = SECFiling.objects.create(
            ticker=self.ticker, form_type='4', filed_at=timezone.now(),
            filer_name='B', transaction_type='sell', accession_number='a2',
        )
        filings = list(SECFiling.objects.filter(ticker=self.ticker))
        self.assertEqual(filings[0].pk, f2.pk)


class WhaleActivityModelTest(TestCase):
    def setUp(self):
        self.ticker = Ticker.objects.create(symbol='AAPL')

    def test_str(self):
        whale = WhaleActivity.objects.create(
            ticker=self.ticker, date=date.today(), signal='bullish', confidence=75,
        )
        self.assertIn('AAPL', str(whale))
        self.assertIn('bullish', str(whale))
        self.assertIn('75%', str(whale))

    def test_unique_together(self):
        WhaleActivity.objects.create(
            ticker=self.ticker, date=date.today(), signal='bullish',
        )
        with self.assertRaises(Exception):
            WhaleActivity.objects.create(
                ticker=self.ticker, date=date.today(), signal='bearish',
            )

    def test_ordering(self):
        w1 = WhaleActivity.objects.create(
            ticker=self.ticker, date=date.today() - timedelta(days=1), signal='neutral',
        )
        w2 = WhaleActivity.objects.create(
            ticker=self.ticker, date=date.today(), signal='bullish',
        )
        whales = list(WhaleActivity.objects.filter(ticker=self.ticker))
        self.assertEqual(whales[0].pk, w2.pk)

    def test_summary_text_with_data(self):
        whale = WhaleActivity.objects.create(
            ticker=self.ticker, date=date.today(), signal='bullish',
            confidence=80, insider_buy_count=3, block_trade_detected=True,
        )
        text = whale.summary_text
        self.assertIn('3 insider buys', text)
        self.assertIn('block trade', text)

    def test_summary_text_neutral(self):
        whale = WhaleActivity.objects.create(
            ticker=self.ticker, date=date.today(), signal='neutral',
        )
        self.assertEqual(whale.summary_text, 'Normal activity')


class SECFilingServiceTest(TestCase):
    def setUp(self):
        self.ticker = Ticker.objects.create(symbol='AAPL')

    def test_resolve_cik_cache_hit(self):
        CIKMapping.objects.create(ticker=self.ticker, cik='0000320193')
        cik = SECFilingService._resolve_cik(self.ticker)
        self.assertEqual(cik, '0000320193')

    @patch('analysis.sec_service._sec_get')
    def test_resolve_cik_cache_miss(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            '0': {'cik_str': 320193, 'ticker': 'AAPL', 'title': 'Apple Inc'},
        }
        mock_get.return_value = mock_resp

        cik = SECFilingService._resolve_cik(self.ticker)
        self.assertEqual(cik, '0000320193')
        self.assertTrue(CIKMapping.objects.filter(ticker=self.ticker).exists())

    def test_refresh_sec_data_skips_if_recent(self):
        # Create a recent filing so refresh should skip
        SECFiling.objects.create(
            ticker=self.ticker, form_type='4', filed_at=timezone.now(),
            filer_name='Test', transaction_type='buy', accession_number='recent1',
        )
        with patch.object(SECFilingService, '_resolve_cik') as mock_cik:
            SECFilingService.refresh_sec_data(self.ticker)
            mock_cik.assert_not_called()

    @patch('analysis.sec_service._sec_get')
    def test_sec_error_handling(self, mock_get):
        """SEC 403 error should not raise, just return empty."""
        CIKMapping.objects.create(ticker=self.ticker, cik='0000320193')
        mock_get.side_effect = requests.exceptions.HTTPError("403 Forbidden")
        # Should not raise
        result = SECFilingService.fetch_form4_filings(self.ticker)
        self.assertEqual(result, [])

    @patch('analysis.sec_service._sec_get')
    def test_fetch_form4_dedup(self, mock_get):
        """Duplicate accession numbers should not create duplicate records."""
        CIKMapping.objects.create(ticker=self.ticker, cik='0000320193')
        # Pre-existing filing
        SECFiling.objects.create(
            ticker=self.ticker, form_type='4', filed_at=timezone.now(),
            filer_name='Tim Cook', transaction_type='buy',
            accession_number='existing_0',
        )
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'hits': {'hits': [{
                '_id': 'existing',
                '_source': {
                    'file_date': timezone.now().isoformat(),
                    'display_names': ['Tim Cook'],
                    'accession_no': 'existing',
                },
            }]}
        }
        mock_get.return_value = mock_resp
        result = SECFilingService.fetch_form4_filings(self.ticker)
        # Should not create a new filing
        self.assertEqual(len(result), 0)


class WhaleDetectionServiceTest(TestCase):
    def setUp(self):
        self.ticker = Ticker.objects.create(
            symbol='AAPL', company_name='Apple Inc.',
            last_price=Decimal('180.00'), day_change_pct=Decimal('0.2'),
        )
        # Create some price history for volume analysis
        for i in range(21):
            PriceHistory.objects.create(
                ticker=self.ticker,
                date=date.today() - timedelta(days=20 - i),
                open=Decimal('175.00'), high=Decimal('182.00'),
                low=Decimal('174.00'), close=Decimal('180.00'),
                volume=1000000,
            )

    def test_cluster_buying_bullish(self):
        """3+ insiders buying in 14 days should produce a bullish signal."""
        for i, name in enumerate(['Tim Cook', 'Luca Maestri', 'Jeff Williams']):
            SECFiling.objects.create(
                ticker=self.ticker, form_type='4',
                filed_at=timezone.now() - timedelta(days=i),
                filer_name=name, filer_title='SVP',
                transaction_type='buy',
                shares=Decimal('10000'), total_value=Decimal('1800000'),
                accession_number=f'cluster_{i}',
            )
        whale = WhaleDetectionService.detect_whale_activity(self.ticker)
        self.assertIsNotNone(whale)
        self.assertEqual(whale.signal, 'bullish')
        self.assertGreaterEqual(whale.confidence, 40)
        self.assertEqual(whale.insider_buy_count, 3)
        self.assertTrue(whale.details.get('cluster_buy'))

    def test_single_insider_sale_bearish(self):
        """Large insider sales should push toward bearish."""
        for i in range(4):
            SECFiling.objects.create(
                ticker=self.ticker, form_type='4',
                filed_at=timezone.now() - timedelta(days=i),
                filer_name=f'Seller {i}', transaction_type='sell',
                shares=Decimal('50000'), total_value=Decimal('9000000'),
                accession_number=f'sell_{i}',
            )
        whale = WhaleDetectionService.detect_whale_activity(self.ticker)
        self.assertIsNotNone(whale)
        self.assertEqual(whale.signal, 'bearish')
        self.assertEqual(whale.insider_sell_count, 4)

    def test_13d_filing_boosts_confidence(self):
        """13D filing should boost confidence."""
        SECFiling.objects.create(
            ticker=self.ticker, form_type='SC 13D',
            filed_at=timezone.now() - timedelta(days=10),
            filer_name='Activist Fund', transaction_type='acquisition',
            accession_number='13d_1',
        )
        # Also add an insider buy to make it bullish
        SECFiling.objects.create(
            ticker=self.ticker, form_type='4',
            filed_at=timezone.now(), filer_name='CEO',
            transaction_type='buy', shares=Decimal('5000'),
            total_value=Decimal('900000'), accession_number='buy_1',
        )
        whale = WhaleDetectionService.detect_whale_activity(self.ticker)
        self.assertIsNotNone(whale)
        self.assertTrue(whale.has_13d_filing)
        # 13D should boost confidence by 20
        self.assertGreaterEqual(whale.confidence, 20)

    def test_normal_activity_neutral(self):
        """No filings, no unusual options, normal volume -> neutral."""
        whale = WhaleDetectionService.detect_whale_activity(self.ticker)
        self.assertIsNotNone(whale)
        self.assertEqual(whale.signal, 'neutral')
        self.assertLessEqual(whale.confidence, 20)

    def test_block_trade_detected(self):
        """Volume spike > 5x average should flag block trade."""
        # Set today's volume very high
        today_price = PriceHistory.objects.filter(
            ticker=self.ticker, date=date.today()
        ).first()
        if today_price:
            today_price.volume = 10000000  # 10x average of 1M
            today_price.save()

        whale = WhaleDetectionService.detect_whale_activity(self.ticker)
        self.assertIsNotNone(whale)
        self.assertTrue(whale.block_trade_detected)

    def test_store_daily_snapshot_updates(self):
        """Running twice on same day should update, not duplicate."""
        whale1 = WhaleDetectionService.detect_whale_activity(self.ticker)
        whale2 = WhaleDetectionService.detect_whale_activity(self.ticker)
        self.assertEqual(whale1.pk, whale2.pk)
        count = WhaleActivity.objects.filter(ticker=self.ticker, date=date.today()).count()
        self.assertEqual(count, 1)

    def test_sec_weighted_highest(self):
        """SEC signals should be 50% of final score."""
        # Create strong bullish SEC signals
        for i, name in enumerate(['CEO', 'CFO', 'COO', 'CTO']):
            SECFiling.objects.create(
                ticker=self.ticker, form_type='4',
                filed_at=timezone.now() - timedelta(days=i),
                filer_name=name, transaction_type='buy',
                shares=Decimal('10000'), total_value=Decimal('1800000'),
                accession_number=f'sec_weight_{i}',
            )
        whale = WhaleDetectionService.detect_whale_activity(self.ticker)
        # With strong SEC signals (score ~100) and neutral options/volume (50 each),
        # weighted should be: 100*0.5 + 50*0.3 + 50*0.2 = 75, clearly bullish
        self.assertEqual(whale.signal, 'bullish')
        self.assertIn('weighted_score', whale.details)
        self.assertGreater(whale.details['weighted_score'], 60)


class WhaleHoldingsViewTest(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.ticker = Ticker.objects.create(
            symbol='AAPL', company_name='Apple Inc.',
            last_price=Decimal('180.00'),
        )
        self.portfolio = Portfolio.objects.create(name='Test', user=self.user)
        Lot.objects.create(
            portfolio=self.portfolio, ticker=self.ticker,
            shares=Decimal('10'), cost_basis=Decimal('150.00'),
            purchase_date=date(2024, 1, 1),
        )

    def test_holdings_shows_whale_indicator(self):
        WhaleActivity.objects.create(
            ticker=self.ticker, date=date.today(),
            signal='bullish', confidence=78,
            insider_buy_count=3, details={'summary': '3 insider buys'},
        )
        response = self.client.get(reverse('portfolio_detail', args=[self.portfolio.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '&#x1F40B;')  # whale emoji
        self.assertContains(response, '78%')

    def test_holdings_no_whale_data(self):
        response = self.client.get(reverse('portfolio_detail', args=[self.portfolio.pk]))
        self.assertEqual(response.status_code, 200)
        # Should show -- for whale column, not crash
        content = response.content.decode()
        self.assertIn('Whale', content)  # column header exists

    def test_whale_detail_shows_insider_table(self):
        WhaleActivity.objects.create(
            ticker=self.ticker, date=date.today(),
            signal='bullish', confidence=80,
            insider_buy_count=2, has_13d_filing=True,
            details={
                'recent_form4s': [
                    {'date': '2026-03-20', 'name': 'Tim Cook', 'title': 'CEO',
                     'type': 'buy', 'shares': 10000, 'value': 1800000},
                ],
                'cluster_buy': False,
                'summary': '2 insider buys + activist position',
            },
        )
        response = self.client.get(reverse('portfolio_detail', args=[self.portfolio.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Insider Activity')
        self.assertContains(response, 'Tim Cook')
        self.assertContains(response, 'Activist Position (13D)')

    def test_bearish_whale_shows_down_arrow(self):
        WhaleActivity.objects.create(
            ticker=self.ticker, date=date.today(),
            signal='bearish', confidence=65,
            insider_sell_count=3,
        )
        response = self.client.get(reverse('portfolio_detail', args=[self.portfolio.pk]))
        self.assertContains(response, '&darr;')
        self.assertContains(response, '65%')

    def test_neutral_whale_shows_grey_emoji(self):
        WhaleActivity.objects.create(
            ticker=self.ticker, date=date.today(),
            signal='neutral', confidence=5,
        )
        response = self.client.get(reverse('portfolio_detail', args=[self.portfolio.pk]))
        # Neutral shows a grey whale emoji (no arrow)
        self.assertContains(response, '&#x1F40B;')
        # But no directional arrows
        self.assertNotContains(response, '&#x1F40B;&uarr;')
        self.assertNotContains(response, '&#x1F40B;&darr;')
