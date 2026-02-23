from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from analysis.models import AIAnalysis, IndicatorSnapshot
from analysis.services import AIAnalysisService, TechnicalIndicatorService
from market.models import NewsArticle, PriceHistory
from portfolio.models import Ticker


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
        WatchlistItem.objects.create(ticker=ticker)
        response = self.client.post(reverse('watchlist_add'), {'symbol': 'AAPL'})
        self.assertEqual(response.status_code, 400)

    def test_remove_from_watchlist(self):
        ticker = Ticker.objects.create(symbol='AAPL')
        from portfolio.models import WatchlistItem
        item = WatchlistItem.objects.create(ticker=ticker)
        response = self.client.post(reverse('watchlist_remove', args=[item.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WatchlistItem.objects.count(), 0)

    def test_remove_requires_post(self):
        ticker = Ticker.objects.create(symbol='AAPL')
        from portfolio.models import WatchlistItem
        item = WatchlistItem.objects.create(ticker=ticker)
        response = self.client.get(reverse('watchlist_remove', args=[item.pk]))
        self.assertEqual(response.status_code, 405)

    def test_watchlist_shows_items(self):
        ticker = Ticker.objects.create(symbol='AAPL', company_name='Apple Inc.',
                                        last_price=Decimal('178.50'))
        from portfolio.models import WatchlistItem
        WatchlistItem.objects.create(ticker=ticker, notes='Watching for dip')
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
