from datetime import date, datetime, time
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from .forms import LotForm, PortfolioForm
from .models import Lot, Portfolio, ReportSchedule, Ticker, WatchlistItem


class LoggedInTestCase(TestCase):
    """Base test class that provides an authenticated client."""
    def setUp(self):
        self.user = User.objects.create_user('testuser', password='testpass')
        self.client = Client()
        self.client.force_login(self.user)


class TickerModelTest(TestCase):
    def test_create_ticker(self):
        ticker = Ticker.objects.create(
            symbol='AAPL',
            company_name='Apple Inc.',
            sector='Technology',
            last_price=Decimal('178.50'),
        )
        self.assertEqual(str(ticker), 'AAPL')
        self.assertEqual(ticker.company_name, 'Apple Inc.')

    def test_ticker_symbol_unique(self):
        Ticker.objects.create(symbol='AAPL')
        with self.assertRaises(Exception):
            Ticker.objects.create(symbol='AAPL')

    def test_ticker_ordering(self):
        Ticker.objects.create(symbol='MSFT')
        Ticker.objects.create(symbol='AAPL')
        tickers = list(Ticker.objects.values_list('symbol', flat=True))
        self.assertEqual(tickers, ['AAPL', 'MSFT'])


class PortfolioModelTest(TestCase):
    def setUp(self):
        self.portfolio = Portfolio.objects.create(
            name='Test Portfolio', notes='Testing'
        )
        self.ticker = Ticker.objects.create(
            symbol='AAPL', company_name='Apple Inc.', last_price=Decimal('200.00')
        )

    def test_create_portfolio(self):
        self.assertEqual(str(self.portfolio), 'Test Portfolio')

    def test_portfolio_total_cost(self):
        Lot.objects.create(
            portfolio=self.portfolio,
            ticker=self.ticker,
            shares=Decimal('100'),
            cost_basis=Decimal('150.00'),
            purchase_date=date(2024, 1, 15),
        )
        Lot.objects.create(
            portfolio=self.portfolio,
            ticker=self.ticker,
            shares=Decimal('50'),
            cost_basis=Decimal('160.00'),
            purchase_date=date(2024, 6, 1),
        )
        self.assertEqual(self.portfolio.total_cost, Decimal('23000.00'))

    def test_portfolio_total_value(self):
        Lot.objects.create(
            portfolio=self.portfolio,
            ticker=self.ticker,
            shares=Decimal('100'),
            cost_basis=Decimal('150.00'),
            purchase_date=date(2024, 1, 15),
        )
        self.assertEqual(self.portfolio.total_value, Decimal('20000.00'))

    def test_portfolio_gain_loss(self):
        Lot.objects.create(
            portfolio=self.portfolio,
            ticker=self.ticker,
            shares=Decimal('100'),
            cost_basis=Decimal('150.00'),
            purchase_date=date(2024, 1, 15),
        )
        self.assertEqual(self.portfolio.total_gain_loss, Decimal('5000.00'))
        self.assertAlmostEqual(
            float(self.portfolio.total_gain_loss_pct), 33.33, places=1
        )

    def test_get_holdings(self):
        ticker2 = Ticker.objects.create(symbol='MSFT', last_price=Decimal('420.00'))
        Lot.objects.create(
            portfolio=self.portfolio, ticker=self.ticker,
            shares=Decimal('100'), cost_basis=Decimal('150.00'),
            purchase_date=date(2024, 1, 15),
        )
        Lot.objects.create(
            portfolio=self.portfolio, ticker=self.ticker,
            shares=Decimal('50'), cost_basis=Decimal('160.00'),
            purchase_date=date(2024, 6, 1),
        )
        Lot.objects.create(
            portfolio=self.portfolio, ticker=ticker2,
            shares=Decimal('30'), cost_basis=Decimal('380.00'),
            purchase_date=date(2024, 3, 1),
        )
        holdings = self.portfolio.get_holdings()
        self.assertEqual(len(holdings), 2)
        # Sorted by symbol
        self.assertEqual(holdings[0]['ticker'].symbol, 'AAPL')
        self.assertEqual(holdings[1]['ticker'].symbol, 'MSFT')
        # AAPL: 150 shares, cost 23000
        self.assertEqual(holdings[0]['total_shares'], Decimal('150'))
        self.assertEqual(holdings[0]['total_cost'], Decimal('23000.00'))
        self.assertEqual(holdings[0]['current_value'], Decimal('30000.00'))
        self.assertEqual(len(holdings[0]['lots']), 2)


class LotModelTest(TestCase):
    def setUp(self):
        self.portfolio = Portfolio.objects.create(name='Test')
        self.ticker = Ticker.objects.create(
            symbol='MSFT', last_price=Decimal('420.00')
        )
        self.lot = Lot.objects.create(
            portfolio=self.portfolio,
            ticker=self.ticker,
            shares=Decimal('50'),
            cost_basis=Decimal('380.00'),
            purchase_date=date(2024, 3, 1),
        )

    def test_str(self):
        self.assertIn('50', str(self.lot))
        self.assertIn('MSFT', str(self.lot))
        self.assertIn('380.00', str(self.lot))

    def test_total_cost(self):
        self.assertEqual(self.lot.total_cost, Decimal('19000.00'))

    def test_current_value(self):
        self.assertEqual(self.lot.current_value, Decimal('21000.00'))

    def test_gain_loss(self):
        self.assertEqual(self.lot.gain_loss, Decimal('2000.00'))

    def test_gain_loss_pct(self):
        expected = (Decimal('2000') / Decimal('19000')) * Decimal('100')
        self.assertEqual(self.lot.gain_loss_pct, expected)

    def test_no_price_returns_none(self):
        ticker_no_price = Ticker.objects.create(symbol='XXX')
        lot = Lot.objects.create(
            portfolio=self.portfolio,
            ticker=ticker_no_price,
            shares=Decimal('10'),
            cost_basis=Decimal('100.00'),
            purchase_date=date(2024, 1, 1),
        )
        self.assertIsNone(lot.current_value)
        self.assertIsNone(lot.gain_loss)
        self.assertIsNone(lot.gain_loss_pct)

    def test_lot_ordering(self):
        lot2 = Lot.objects.create(
            portfolio=self.portfolio,
            ticker=self.ticker,
            shares=Decimal('10'),
            cost_basis=Decimal('400.00'),
            purchase_date=date(2024, 9, 1),
        )
        lots = list(self.portfolio.lots.all())
        self.assertEqual(lots[0], lot2)  # newer date first
        self.assertEqual(lots[1], self.lot)


class DashboardViewTest(LoggedInTestCase):
    def test_dashboard_loads(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dashboard')

    def test_dashboard_shows_portfolio_count(self):
        Portfolio.objects.create(name='P1')
        Portfolio.objects.create(name='P2')
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, '2')


class PortfolioFormTest(TestCase):
    def test_valid_form(self):
        form = PortfolioForm(data={'name': 'My Portfolio', 'notes': ''})
        self.assertTrue(form.is_valid())

    def test_name_required(self):
        form = PortfolioForm(data={'name': '', 'notes': ''})
        self.assertFalse(form.is_valid())
        self.assertIn('name', form.errors)


class LotFormTest(TestCase):
    def setUp(self):
        self.portfolio = Portfolio.objects.create(name='Test')
        self.ticker = Ticker.objects.create(symbol='AAPL')

    def test_valid_form_existing_ticker(self):
        form = LotForm(data={
            'symbol': 'AAPL',
            'shares': '100',
            'cost_basis': '150.00',
            'purchase_date': '2024-01-15',
            'notes': '',
        }, portfolio=self.portfolio)
        self.assertTrue(form.is_valid())
        lot = form.save()
        self.assertEqual(lot.ticker.symbol, 'AAPL')
        self.assertEqual(lot.portfolio, self.portfolio)

    def test_creates_new_ticker(self):
        form = LotForm(data={
            'symbol': 'NVDA',
            'shares': '10',
            'cost_basis': '800.00',
            'purchase_date': '2024-06-01',
            'notes': '',
        }, portfolio=self.portfolio)
        self.assertTrue(form.is_valid())
        lot = form.save()
        self.assertEqual(lot.ticker.symbol, 'NVDA')
        self.assertTrue(Ticker.objects.filter(symbol='NVDA').exists())

    def test_symbol_uppercased(self):
        form = LotForm(data={
            'symbol': 'aapl',
            'shares': '10',
            'cost_basis': '150.00',
            'purchase_date': '2024-01-15',
            'notes': '',
        }, portfolio=self.portfolio)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['symbol'], 'AAPL')

    def test_symbol_required(self):
        form = LotForm(data={
            'symbol': '',
            'shares': '10',
            'cost_basis': '150.00',
            'purchase_date': '2024-01-15',
            'notes': '',
        }, portfolio=self.portfolio)
        self.assertFalse(form.is_valid())


class PortfolioListViewTest(LoggedInTestCase):

    def test_list_page_loads(self):
        response = self.client.get(reverse('portfolio_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Portfolios')

    def test_list_shows_portfolios(self):
        Portfolio.objects.create(name='Tech Growth')
        response = self.client.get(reverse('portfolio_list'))
        self.assertContains(response, 'Tech Growth')


class PortfolioDetailViewTest(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.portfolio = Portfolio.objects.create(name='Test Portfolio')
        self.ticker = Ticker.objects.create(
            symbol='AAPL', company_name='Apple Inc.', last_price=Decimal('178.50')
        )
        Lot.objects.create(
            portfolio=self.portfolio, ticker=self.ticker,
            shares=Decimal('100'), cost_basis=Decimal('150.00'),
            purchase_date=date(2024, 1, 15),
        )

    def test_detail_page_loads(self):
        response = self.client.get(reverse('portfolio_detail', args=[self.portfolio.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Portfolio')
        self.assertContains(response, 'AAPL')

    def test_detail_404_for_missing(self):
        response = self.client.get(reverse('portfolio_detail', args=[9999]))
        self.assertEqual(response.status_code, 404)


class PortfolioCRUDViewTest(LoggedInTestCase):

    def test_create_portfolio(self):
        response = self.client.post(reverse('portfolio_create'), {
            'name': 'New Portfolio',
            'notes': 'Test notes',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Portfolio.objects.filter(name='New Portfolio').exists())

    def test_edit_portfolio(self):
        portfolio = Portfolio.objects.create(name='Old Name')
        response = self.client.post(reverse('portfolio_edit', args=[portfolio.pk]), {
            'name': 'New Name',
            'notes': '',
        })
        self.assertEqual(response.status_code, 302)
        portfolio.refresh_from_db()
        self.assertEqual(portfolio.name, 'New Name')

    def test_delete_portfolio(self):
        portfolio = Portfolio.objects.create(name='To Delete')
        response = self.client.post(reverse('portfolio_delete', args=[portfolio.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Portfolio.objects.filter(pk=portfolio.pk).exists())


class LotCRUDViewTest(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.portfolio = Portfolio.objects.create(name='Test')
        self.ticker = Ticker.objects.create(symbol='AAPL')

    def test_create_lot(self):
        response = self.client.post(
            reverse('lot_create', args=[self.portfolio.pk]),
            {
                'symbol': 'AAPL',
                'shares': '100',
                'cost_basis': '150.00',
                'purchase_date': '2024-01-15',
                'notes': '',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.portfolio.lots.count(), 1)

    def test_edit_lot(self):
        lot = Lot.objects.create(
            portfolio=self.portfolio, ticker=self.ticker,
            shares=Decimal('100'), cost_basis=Decimal('150.00'),
            purchase_date=date(2024, 1, 15),
        )
        response = self.client.post(reverse('lot_edit', args=[lot.pk]), {
            'symbol': 'AAPL',
            'shares': '200',
            'cost_basis': '155.00',
            'purchase_date': '2024-01-15',
            'notes': 'Updated',
        })
        self.assertEqual(response.status_code, 302)
        lot.refresh_from_db()
        self.assertEqual(lot.shares, Decimal('200'))

    def test_delete_lot(self):
        lot = Lot.objects.create(
            portfolio=self.portfolio, ticker=self.ticker,
            shares=Decimal('10'), cost_basis=Decimal('100.00'),
            purchase_date=date(2024, 1, 1),
        )
        response = self.client.post(reverse('lot_delete', args=[lot.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.portfolio.lots.count(), 0)


class TickerSearchViewTest(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        Ticker.objects.create(symbol='AAPL', company_name='Apple Inc.')
        Ticker.objects.create(symbol='AMZN', company_name='Amazon.com Inc.')
        Ticker.objects.create(symbol='MSFT', company_name='Microsoft Corporation')

    def test_search_returns_matches(self):
        response = self.client.get(reverse('ticker_search'), {'q': 'A'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        symbols = [t['symbol'] for t in data]
        self.assertIn('AAPL', symbols)
        self.assertIn('AMZN', symbols)
        self.assertNotIn('MSFT', symbols)

    def test_search_empty_query(self):
        response = self.client.get(reverse('ticker_search'), {'q': ''})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])


class WatchlistItemModelTest(TestCase):
    def test_create_watchlist_item(self):
        ticker = Ticker.objects.create(symbol='AAPL')
        item = WatchlistItem.objects.create(ticker=ticker, notes='Watching for dip')
        self.assertEqual(str(item), 'Watchlist: AAPL')
        self.assertIsNotNone(item.added_at)
        self.assertEqual(item.notes, 'Watching for dip')

    def test_unique_ticker(self):
        ticker = Ticker.objects.create(symbol='AAPL')
        WatchlistItem.objects.create(ticker=ticker)
        with self.assertRaises(Exception):
            WatchlistItem.objects.create(ticker=ticker)

    def test_ordering(self):
        t1 = Ticker.objects.create(symbol='AAPL')
        t2 = Ticker.objects.create(symbol='MSFT')
        WatchlistItem.objects.create(ticker=t1)
        WatchlistItem.objects.create(ticker=t2)
        items = list(WatchlistItem.objects.all())
        # Most recent first
        self.assertEqual(items[0].ticker.symbol, 'MSFT')


class EmailReportViewTest(LoggedInTestCase):
    def test_get_not_allowed(self):
        response = self.client.get(reverse('send_email_report'))
        self.assertEqual(response.status_code, 405)

    @patch('portfolio.report_service.EmailReportService')
    def test_post_sends_report(self, mock_service_cls):
        mock_service_cls.generate_and_send.return_value = True
        response = self.client.post(reverse('send_email_report'))
        self.assertEqual(response.status_code, 302)
        mock_service_cls.generate_and_send.assert_called_once()

    @patch('portfolio.report_service.EmailReportService')
    def test_post_htmx_returns_success_html(self, mock_service_cls):
        mock_service_cls.generate_and_send.return_value = True
        response = self.client.post(
            reverse('send_email_report'),
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('Report sent successfully', response.content.decode())

    @patch('portfolio.report_service.EmailReportService')
    def test_post_handles_error(self, mock_service_cls):
        mock_service_cls.generate_and_send.side_effect = Exception('SMTP failed')
        response = self.client.post(
            reverse('send_email_report'),
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(response.status_code, 500)
        self.assertIn('Failed to send report', response.content.decode())

    @patch('portfolio.report_service.EmailReportService')
    def test_post_error_redirects_non_htmx(self, mock_service_cls):
        mock_service_cls.generate_and_send.side_effect = Exception('SMTP failed')
        response = self.client.post(reverse('send_email_report'))
        self.assertEqual(response.status_code, 302)


class EmailReportServiceTest(TestCase):
    def setUp(self):
        self.portfolio = Portfolio.objects.create(name='Test Portfolio')
        self.ticker = Ticker.objects.create(
            symbol='AAPL', company_name='Apple Inc.',
            last_price=Decimal('200.00'), sector='Technology',
        )
        Lot.objects.create(
            portfolio=self.portfolio, ticker=self.ticker,
            shares=Decimal('100'), cost_basis=Decimal('150.00'),
            purchase_date=date(2024, 1, 15),
        )

    def test_gather_report_data(self):
        from portfolio.report_service import EmailReportService
        data = EmailReportService.gather_report_data()
        self.assertEqual(len(data['portfolios']), 1)
        pdata = data['portfolios'][0]
        self.assertEqual(pdata['portfolio'].name, 'Test Portfolio')
        self.assertEqual(len(pdata['holdings_data']), 1)
        self.assertEqual(pdata['holdings_data'][0]['holding']['ticker'].symbol, 'AAPL')
        self.assertIn('generated_at', data)

    def test_generate_allocation_chart(self):
        from portfolio.report_service import ReportChartService
        holdings = self.portfolio.get_holdings()
        result = ReportChartService.generate_portfolio_allocation_chart(holdings)
        self.assertIsNotNone(result)
        self.assertTrue(result[:4] == b'\x89PNG')

    def test_generate_gain_loss_chart(self):
        from portfolio.report_service import ReportChartService
        holdings = self.portfolio.get_holdings()
        result = ReportChartService.generate_gain_loss_bar_chart(holdings)
        self.assertIsNotNone(result)
        self.assertTrue(result[:4] == b'\x89PNG')

    def test_generate_allocation_chart_empty(self):
        from portfolio.report_service import ReportChartService
        result = ReportChartService.generate_portfolio_allocation_chart([])
        self.assertIsNone(result)

    def test_generate_opportunity_score_chart(self):
        from portfolio.report_service import ReportChartService
        from analysis.models import IndicatorSnapshot
        snap = IndicatorSnapshot.objects.create(
            ticker=self.ticker, opportunity_score=75,
        )
        holdings = self.portfolio.get_holdings()
        result = ReportChartService.generate_opportunity_score_chart(
            [(holdings[0], snap)]
        )
        self.assertIsNotNone(result)
        self.assertTrue(result[:4] == b'\x89PNG')

    @patch('portfolio.report_service.EmailReportService.refresh_portfolio_data')
    @patch('portfolio.report_service.EmailMessage')
    def test_generate_and_send(self, mock_email_cls, mock_refresh):
        from portfolio.report_service import EmailReportService
        mock_conn = mock_email_cls.return_value.get_connection.return_value
        mock_conn.connection = MagicMock()
        with self.settings(
            REPORT_RECIPIENT_EMAIL='test@example.com',
            DEFAULT_FROM_EMAIL='sender@example.com',
        ):
            EmailReportService.generate_and_send()
            mock_refresh.assert_called_once()
            mock_conn.connection.sendmail.assert_called_once()

    @patch('portfolio.report_service.EmailReportService.refresh_portfolio_data')
    def test_generate_and_send_no_recipient(self, mock_refresh):
        from portfolio.report_service import EmailReportService
        with self.settings(REPORT_RECIPIENT_EMAIL=''):
            with self.assertRaises(ValueError):
                EmailReportService.generate_and_send()


class ReportScheduleModelTest(TestCase):
    def test_create_schedule_defaults(self):
        schedule = ReportSchedule.objects.create(time=time(8, 0))
        self.assertTrue(schedule.enabled)
        self.assertTrue(schedule.monday)
        self.assertTrue(schedule.tuesday)
        self.assertTrue(schedule.wednesday)
        self.assertTrue(schedule.thursday)
        self.assertTrue(schedule.friday)
        self.assertIsNone(schedule.last_run)

    def test_str(self):
        schedule = ReportSchedule.objects.create(
            time=time(8, 0), monday=True, tuesday=False,
            wednesday=True, thursday=False, friday=True,
        )
        s = str(schedule)
        self.assertIn('Mon', s)
        self.assertNotIn('Tue', s)
        self.assertIn('Wed', s)

    def test_is_due_correct_day_and_time(self):
        schedule = ReportSchedule.objects.create(time=time(8, 0))
        # Monday 8:00 AM
        now = datetime(2026, 2, 23, 8, 0, 0)  # Monday
        self.assertTrue(schedule.is_due(now))

    def test_is_due_wrong_day(self):
        schedule = ReportSchedule.objects.create(time=time(8, 0), monday=False)
        now = datetime(2026, 2, 23, 8, 0, 0)  # Monday
        self.assertFalse(schedule.is_due(now))

    def test_is_due_weekend(self):
        schedule = ReportSchedule.objects.create(time=time(8, 0))
        now = datetime(2026, 2, 22, 8, 0, 0)  # Sunday
        self.assertFalse(schedule.is_due(now))

    def test_is_due_wrong_time(self):
        schedule = ReportSchedule.objects.create(time=time(8, 0))
        now = datetime(2026, 2, 23, 10, 0, 0)  # Monday but 10 AM
        self.assertFalse(schedule.is_due(now))

    def test_is_due_already_run_today(self):
        schedule = ReportSchedule.objects.create(time=time(8, 0))
        now = datetime(2026, 2, 23, 8, 0, 0, tzinfo=timezone.get_current_timezone())
        schedule.last_run = now
        schedule.save()
        self.assertFalse(schedule.is_due(now))

    def test_is_due_disabled(self):
        schedule = ReportSchedule.objects.create(time=time(8, 0), enabled=False)
        now = datetime(2026, 2, 23, 8, 0, 0)
        self.assertFalse(schedule.is_due(now))

    def test_is_due_within_window(self):
        schedule = ReportSchedule.objects.create(time=time(8, 0))
        now = datetime(2026, 2, 23, 8, 1, 30)  # 1.5 minutes after
        self.assertTrue(schedule.is_due(now))

    def test_is_due_outside_window(self):
        schedule = ReportSchedule.objects.create(time=time(8, 0))
        now = datetime(2026, 2, 23, 8, 2, 1)  # Just over 2 minutes
        self.assertFalse(schedule.is_due(now))


class ReportScheduleViewTest(LoggedInTestCase):
    def test_create_schedule(self):
        response = self.client.post(reverse('schedule_create'), {
            'time': '08:00',
            'monday': 'on',
            'wednesday': 'on',
            'friday': 'on',
        }, HTTP_HX_REQUEST='true')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ReportSchedule.objects.count(), 1)
        schedule = ReportSchedule.objects.first()
        self.assertEqual(schedule.time, time(8, 0))
        self.assertTrue(schedule.monday)
        self.assertFalse(schedule.tuesday)
        self.assertTrue(schedule.wednesday)

    def test_edit_schedule(self):
        schedule = ReportSchedule.objects.create(time=time(8, 0))
        response = self.client.post(
            reverse('schedule_edit', args=[schedule.pk]),
            {'time': '09:30', 'monday': 'on', 'friday': 'on'},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(response.status_code, 200)
        schedule.refresh_from_db()
        self.assertEqual(schedule.time, time(9, 30))
        self.assertTrue(schedule.monday)
        self.assertFalse(schedule.tuesday)

    def test_delete_schedule(self):
        schedule = ReportSchedule.objects.create(time=time(8, 0))
        response = self.client.post(
            reverse('schedule_delete', args=[schedule.pk]),
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ReportSchedule.objects.count(), 0)

    def test_toggle_schedule(self):
        schedule = ReportSchedule.objects.create(time=time(8, 0), enabled=True)
        response = self.client.post(
            reverse('schedule_toggle', args=[schedule.pk]),
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(response.status_code, 200)
        schedule.refresh_from_db()
        self.assertFalse(schedule.enabled)

    def test_toggle_schedule_enable(self):
        schedule = ReportSchedule.objects.create(time=time(8, 0), enabled=False)
        self.client.post(
            reverse('schedule_toggle', args=[schedule.pk]),
            HTTP_HX_REQUEST='true',
        )
        schedule.refresh_from_db()
        self.assertTrue(schedule.enabled)


class CheckReportSchedulesCommandTest(TestCase):
    @patch('portfolio.report_service.EmailReportService.generate_and_send')
    def test_sends_when_due(self, mock_send):
        schedule = ReportSchedule.objects.create(time=time(8, 0))
        now = datetime(2026, 2, 23, 8, 0, 0, tzinfo=timezone.get_current_timezone())
        with patch('portfolio.management.commands.check_report_schedules.timezone') as mock_tz:
            mock_tz.now.return_value = now
            mock_tz.localtime.return_value = now
            from django.core.management import call_command
            call_command('check_report_schedules', '--once')
        mock_send.assert_called_once()
        schedule.refresh_from_db()
        self.assertIsNotNone(schedule.last_run)

    @patch('portfolio.report_service.EmailReportService.generate_and_send')
    def test_skips_when_not_due(self, mock_send):
        ReportSchedule.objects.create(time=time(8, 0))
        now = datetime(2026, 2, 23, 15, 0, 0, tzinfo=timezone.get_current_timezone())
        with patch('portfolio.management.commands.check_report_schedules.timezone') as mock_tz:
            mock_tz.now.return_value = now
            mock_tz.localtime.return_value = now
            from django.core.management import call_command
            call_command('check_report_schedules', '--once')
        mock_send.assert_not_called()

    @patch('portfolio.report_service.EmailReportService.generate_and_send')
    def test_skips_disabled(self, mock_send):
        ReportSchedule.objects.create(time=time(8, 0), enabled=False)
        now = datetime(2026, 2, 23, 8, 0, 0, tzinfo=timezone.get_current_timezone())
        with patch('portfolio.management.commands.check_report_schedules.timezone') as mock_tz:
            mock_tz.now.return_value = now
            mock_tz.localtime.return_value = now
            from django.core.management import call_command
            call_command('check_report_schedules', '--once')
        mock_send.assert_not_called()
