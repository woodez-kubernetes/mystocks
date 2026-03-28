from decimal import Decimal

from django.conf import settings
from django.db import models


class Ticker(models.Model):
    symbol = models.CharField(max_length=10, unique=True, db_index=True)
    company_name = models.CharField(max_length=200, blank=True)
    sector = models.CharField(max_length=100, blank=True)
    last_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    last_updated = models.DateTimeField(null=True, blank=True)
    day_change = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    day_change_pct = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    market_cap = models.BigIntegerField(null=True, blank=True)
    pe_ratio = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    dividend_yield = models.DecimalField(
        max_digits=6, decimal_places=4, null=True, blank=True
    )
    week_52_high = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    week_52_low = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    avg_volume = models.BigIntegerField(null=True, blank=True)
    prev_close = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )

    class Meta:
        ordering = ['symbol']

    def __str__(self):
        return self.symbol


class Portfolio(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='portfolios',
    )
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def total_cost(self):
        return sum(lot.total_cost for lot in self.lots.select_related('ticker').all())

    @property
    def total_value(self):
        return sum(
            lot.current_value
            for lot in self.lots.select_related('ticker').all()
            if lot.current_value is not None
        )

    @property
    def total_gain_loss(self):
        value = self.total_value
        cost = self.total_cost
        if value is None or cost is None:
            return None
        return value - cost

    @property
    def total_gain_loss_pct(self):
        cost = self.total_cost
        gain = self.total_gain_loss
        if gain is None or cost == 0:
            return None
        return (gain / cost) * 100

    def get_holdings(self):
        """Group lots by ticker and compute per-ticker summary stats."""
        lots = self.lots.select_related('ticker').all()
        holdings_map = {}
        for lot in lots:
            symbol = lot.ticker.symbol
            if symbol not in holdings_map:
                holdings_map[symbol] = {
                    'ticker': lot.ticker,
                    'lots': [],
                    'total_shares': Decimal('0'),
                    'total_cost': Decimal('0'),
                }
            h = holdings_map[symbol]
            h['lots'].append(lot)
            h['total_shares'] += lot.shares
            h['total_cost'] += lot.total_cost

        holdings = []
        for h in holdings_map.values():
            h['avg_cost'] = (
                h['total_cost'] / h['total_shares']
                if h['total_shares'] > 0
                else Decimal('0')
            )
            price = h['ticker'].last_price
            if price is not None:
                h['current_value'] = h['total_shares'] * price
                h['gain_loss'] = h['current_value'] - h['total_cost']
                h['gain_loss_pct'] = (
                    (h['gain_loss'] / h['total_cost']) * Decimal('100')
                    if h['total_cost'] > 0
                    else None
                )
            else:
                h['current_value'] = None
                h['gain_loss'] = None
                h['gain_loss_pct'] = None
            holdings.append(h)

        holdings.sort(key=lambda x: x['ticker'].symbol)
        return holdings


class Lot(models.Model):
    portfolio = models.ForeignKey(
        Portfolio, on_delete=models.CASCADE, related_name='lots'
    )
    ticker = models.ForeignKey(
        Ticker, on_delete=models.CASCADE, related_name='lots'
    )
    shares = models.DecimalField(max_digits=12, decimal_places=4)
    cost_basis = models.DecimalField(max_digits=12, decimal_places=2)
    purchase_date = models.DateField()
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-purchase_date']

    def __str__(self):
        return f"{self.shares} shares of {self.ticker} @ ${self.cost_basis}"

    @property
    def total_cost(self):
        return self.shares * self.cost_basis

    @property
    def current_value(self):
        if self.ticker.last_price is None:
            return None
        return self.shares * self.ticker.last_price

    @property
    def gain_loss(self):
        value = self.current_value
        if value is None:
            return None
        return value - self.total_cost

    @property
    def gain_loss_pct(self):
        cost = self.total_cost
        gain = self.gain_loss
        if gain is None or cost == 0:
            return None
        return (gain / cost) * Decimal('100')


class ReportAuditLog(models.Model):
    sent_at = models.DateTimeField(auto_now_add=True)
    recipient = models.EmailField()
    status = models.CharField(max_length=10, choices=[
        ('success', 'Success'),
        ('error', 'Error'),
    ])
    error_message = models.TextField(blank=True)
    ticker_count = models.PositiveIntegerField(default=0)
    portfolio_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-sent_at']

    def __str__(self):
        return f"Report {self.status} - {self.sent_at}"


class ReportSchedule(models.Model):
    DAY_FIELDS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='report_schedules',
    )
    time = models.TimeField()
    monday = models.BooleanField(default=True)
    tuesday = models.BooleanField(default=True)
    wednesday = models.BooleanField(default=True)
    thursday = models.BooleanField(default=True)
    friday = models.BooleanField(default=True)
    enabled = models.BooleanField(default=True)
    last_run = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['time']

    def __str__(self):
        days = [d[:3].title() for d in self.DAY_FIELDS if getattr(self, d)]
        return f"{self.time.strftime('%I:%M %p')} ({', '.join(days)})"

    def is_due(self, now):
        """Check if this schedule should run at the given datetime."""
        if not self.enabled:
            return False
        weekday = now.weekday()  # 0=Monday
        day_field = self.DAY_FIELDS[weekday] if weekday < 5 else None
        if day_field is None or not getattr(self, day_field):
            return False
        if self.last_run and self.last_run.date() == now.date():
            return False
        current_time = now.time()
        scheduled = self.time
        # Due if current time is within 1 minute after scheduled time
        from datetime import timedelta, datetime as dt
        sched_dt = dt.combine(now.date(), scheduled)
        now_dt = dt.combine(now.date(), current_time)
        diff = (now_dt - sched_dt).total_seconds()
        return 0 <= diff < 120  # 2-minute window


class WatchlistItem(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='watchlist_items',
    )
    ticker = models.ForeignKey(
        Ticker, on_delete=models.CASCADE, related_name='watchlist_entries'
    )
    added_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-added_at']
        unique_together = ('user', 'ticker')

    def __str__(self):
        return f"Watchlist: {self.ticker.symbol}"
