from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand

from portfolio.models import Lot, Portfolio, Ticker


class Command(BaseCommand):
    help = 'Seed the database with sample tickers, a portfolio, and lots'

    def handle(self, *args, **options):
        tickers_data = [
            ('AAPL', 'Apple Inc.', 'Technology', Decimal('178.50')),
            ('MSFT', 'Microsoft Corporation', 'Technology', Decimal('420.00')),
            ('GOOGL', 'Alphabet Inc.', 'Technology', Decimal('165.00')),
            ('NVDA', 'NVIDIA Corporation', 'Technology', Decimal('880.00')),
            ('TSLA', 'Tesla Inc.', 'Consumer Cyclical', Decimal('195.00')),
            ('AMZN', 'Amazon.com Inc.', 'Consumer Cyclical', Decimal('185.00')),
            ('META', 'Meta Platforms Inc.', 'Technology', Decimal('490.00')),
            ('JPM', 'JPMorgan Chase & Co.', 'Financial Services', Decimal('195.00')),
        ]

        tickers = {}
        for symbol, name, sector, price in tickers_data:
            ticker, created = Ticker.objects.get_or_create(
                symbol=symbol,
                defaults={
                    'company_name': name,
                    'sector': sector,
                    'last_price': price,
                },
            )
            tickers[symbol] = ticker
            status = 'Created' if created else 'Already exists'
            self.stdout.write(f'  {status}: {ticker}')

        portfolio, created = Portfolio.objects.get_or_create(
            name='Tech Growth',
            defaults={'notes': 'Long-term tech growth portfolio'},
        )
        status = 'Created' if created else 'Already exists'
        self.stdout.write(f'  {status} portfolio: {portfolio}')

        lots_data = [
            ('AAPL', 100, '135.00', '2024-01-15'),
            ('AAPL', 30, '155.00', '2024-06-20'),
            ('AAPL', 20, '162.50', '2024-09-10'),
            ('MSFT', 50, '380.00', '2024-03-01'),
            ('GOOGL', 25, '140.00', '2024-02-14'),
            ('NVDA', 15, '650.00', '2024-04-10'),
            ('NVDA', 10, '800.00', '2024-08-15'),
            ('TSLA', 40, '210.00', '2024-05-22'),
        ]

        if created:
            for symbol, shares, price, pdate in lots_data:
                lot = Lot.objects.create(
                    portfolio=portfolio,
                    ticker=tickers[symbol],
                    shares=Decimal(str(shares)),
                    cost_basis=Decimal(price),
                    purchase_date=date.fromisoformat(pdate),
                )
                self.stdout.write(f'  Created lot: {lot}')

        self.stdout.write(self.style.SUCCESS('Seed data loaded successfully!'))
