from django.core.management.base import BaseCommand

from market.services import StockDataService


class Command(BaseCommand):
    help = 'Refresh price data for all tickers in portfolios'

    def add_arguments(self, parser):
        parser.add_argument(
            '--symbol',
            type=str,
            help='Refresh a specific ticker symbol only',
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=1.0,
            help='Seconds to wait between API calls (default: 1.0)',
        )

    def handle(self, *args, **options):
        symbol = options.get('symbol')

        if symbol:
            from portfolio.models import Ticker
            try:
                ticker = Ticker.objects.get(symbol=symbol.upper())
            except Ticker.DoesNotExist:
                self.stderr.write(self.style.ERROR(f'Ticker "{symbol}" not found.'))
                return
            self.stdout.write(f'Refreshing {ticker.symbol}...')
            StockDataService.refresh_ticker(ticker)
            self.stdout.write(self.style.SUCCESS(
                f'  {ticker.symbol}: ${ticker.last_price}'
            ))
        else:
            delay = options['delay']
            self.stdout.write(f'Refreshing all portfolio tickers (delay={delay}s)...')
            results = StockDataService.refresh_all(sleep_between=delay)

            for sym, ok in results:
                if ok:
                    self.stdout.write(self.style.SUCCESS(f'  {sym}: OK'))
                else:
                    self.stdout.write(self.style.ERROR(f'  {sym}: FAILED'))

            success = sum(1 for _, ok in results if ok)
            failed = sum(1 for _, ok in results if not ok)
            self.stdout.write(
                self.style.SUCCESS(f'\nDone. {success} refreshed, {failed} failed.')
            )
