from decimal import Decimal

from django.db import models


SIGNAL_CHOICES = [
    ('buy', 'Buy'),
    ('hold', 'Hold'),
    ('sell', 'Sell'),
]

TRANSACTION_TYPE_CHOICES = [
    ('buy', 'Buy'),
    ('sell', 'Sell'),
    ('exercise', 'Exercise'),
    ('acquisition', 'Acquisition'),
    ('disposition', 'Disposition'),
]

WHALE_SIGNAL_CHOICES = [
    ('bullish', 'Bullish'),
    ('bearish', 'Bearish'),
    ('neutral', 'Neutral'),
]


class IndicatorSnapshot(models.Model):
    ticker = models.OneToOneField(
        'portfolio.Ticker', on_delete=models.CASCADE, related_name='indicators'
    )
    computed_at = models.DateTimeField(auto_now=True)

    # RSI
    rsi = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    rsi_signal = models.CharField(max_length=4, choices=SIGNAL_CHOICES, default='hold')

    # MACD
    macd = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    macd_signal_line = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    macd_histogram = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    macd_signal = models.CharField(max_length=4, choices=SIGNAL_CHOICES, default='hold')

    # Bollinger Bands
    bb_upper = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    bb_middle = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    bb_lower = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    bb_signal = models.CharField(max_length=4, choices=SIGNAL_CHOICES, default='hold')

    # Moving Averages
    sma_50 = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    sma_200 = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    sma_signal = models.CharField(max_length=4, choices=SIGNAL_CHOICES, default='hold')

    # Volume
    volume_ratio = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    volume_signal = models.CharField(max_length=4, choices=SIGNAL_CHOICES, default='hold')

    # Sentiment
    sentiment_score = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    sentiment_signal = models.CharField(max_length=4, choices=SIGNAL_CHOICES, default='hold')

    # Composite score
    opportunity_score = models.IntegerField(default=50)

    # Price target range
    buy_target = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    sell_target = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return f'{self.ticker.symbol} score={self.opportunity_score}'

    @property
    def signal_summary(self):
        """Return list of (label, signal) tuples for all indicators."""
        signals = [
            ('RSI', self.rsi_signal),
            ('MACD', self.macd_signal),
            ('BB', self.bb_signal),
            ('SMA', self.sma_signal),
            ('Vol', self.volume_signal),
            ('Sent', self.sentiment_signal),
        ]
        # Include options signal if available
        try:
            opts = self.ticker.options_snapshot
            if opts:
                signals.append(('Opt', opts.options_signal))
        except Exception:
            pass
        return signals

    class Meta:
        ordering = ['-opportunity_score']


class OptionsSnapshot(models.Model):
    ticker = models.OneToOneField(
        'portfolio.Ticker', on_delete=models.CASCADE, related_name='options_snapshot'
    )
    put_call_volume_ratio = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True
    )
    put_call_oi_ratio = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True
    )
    iv_skew = models.DecimalField(
        max_digits=6, decimal_places=4, null=True, blank=True
    )
    max_pain = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    has_unusual_activity = models.BooleanField(default=False)
    unusual_activity_details = models.JSONField(default=list, blank=True)
    expirations_analyzed = models.JSONField(default=list, blank=True)
    options_signal = models.CharField(
        max_length=4, choices=SIGNAL_CHOICES, default='hold'
    )
    options_score = models.IntegerField(default=50)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.ticker.symbol} options score={self.options_score}'

    class Meta:
        ordering = ['-options_score']


class AIAnalysis(models.Model):
    ticker = models.OneToOneField(
        'portfolio.Ticker', on_delete=models.CASCADE, related_name='ai_analysis'
    )
    analysis_text = models.TextField()
    model_name = models.CharField(max_length=100, default='llama3.2:1b')
    generated_at = models.DateTimeField(auto_now=True)
    prompt_hash = models.CharField(max_length=64, blank=True)

    class Meta:
        verbose_name_plural = 'AI analyses'

    def __str__(self):
        return f'{self.ticker.symbol} AI analysis ({self.generated_at})'


class PortfolioAnalysis(models.Model):
    portfolio = models.OneToOneField(
        'portfolio.Portfolio', on_delete=models.CASCADE, related_name='ai_portfolio_analysis'
    )
    top_picks_text = models.TextField(blank=True)
    top_pick_symbols = models.JSONField(default=list, blank=True)
    portfolio_analysis_text = models.TextField(blank=True)
    model_name = models.CharField(max_length=100, default='llama3.2:1b')
    generated_at = models.DateTimeField(auto_now=True)
    prompt_hash = models.CharField(max_length=64, blank=True)

    class Meta:
        verbose_name_plural = 'Portfolio analyses'

    def __str__(self):
        return f'{self.portfolio.name} portfolio analysis ({self.generated_at})'


class CIKMapping(models.Model):
    ticker = models.OneToOneField(
        'portfolio.Ticker', on_delete=models.CASCADE, related_name='cik_mapping'
    )
    cik = models.CharField(max_length=10)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.ticker.symbol} -> CIK {self.cik}'


class SECFiling(models.Model):
    ticker = models.ForeignKey(
        'portfolio.Ticker', on_delete=models.CASCADE, related_name='sec_filings'
    )
    form_type = models.CharField(max_length=20)
    filed_at = models.DateTimeField()
    filer_name = models.CharField(max_length=300)
    filer_title = models.CharField(max_length=200, blank=True)
    transaction_type = models.CharField(max_length=15, choices=TRANSACTION_TYPE_CHOICES)
    shares = models.DecimalField(max_digits=16, decimal_places=4, null=True, blank=True)
    price_per_share = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    total_value = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    ownership_pct = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    accession_number = models.CharField(max_length=30)
    raw_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('ticker', 'accession_number')
        ordering = ['-filed_at']

    def __str__(self):
        return f'{self.ticker.symbol} {self.form_type} by {self.filer_name} ({self.filed_at:%Y-%m-%d})'


class WhaleActivity(models.Model):
    ticker = models.ForeignKey(
        'portfolio.Ticker', on_delete=models.CASCADE, related_name='whale_activities'
    )
    date = models.DateField()
    signal = models.CharField(max_length=10, choices=WHALE_SIGNAL_CHOICES, default='neutral')
    confidence = models.IntegerField(default=0)

    # SEC filing signals
    insider_buy_count = models.IntegerField(default=0)
    insider_sell_count = models.IntegerField(default=0)
    insider_net_value = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal('0'))
    institutional_change_pct = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    has_13d_filing = models.BooleanField(default=False)

    # Options/volume signals
    options_volume_ratio = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    oi_change_ratio = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True
    )
    block_trade_detected = models.BooleanField(default=False)
    volume_price_divergence = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True
    )

    # Combined
    details = models.JSONField(default=dict, blank=True)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('ticker', 'date')
        ordering = ['-date']
        verbose_name_plural = 'Whale activities'

    def __str__(self):
        return f'{self.ticker.symbol} {self.date} {self.signal} ({self.confidence}%)'

    @property
    def summary_text(self):
        parts = []
        if self.insider_buy_count:
            parts.append(f"{self.insider_buy_count} insider buy{'s' if self.insider_buy_count > 1 else ''}")
        if self.insider_sell_count:
            parts.append(f"{self.insider_sell_count} insider sell{'s' if self.insider_sell_count > 1 else ''}")
        if self.has_13d_filing:
            parts.append("activist position")
        if self.options_volume_ratio and self.options_volume_ratio > 3:
            parts.append("unusual options volume")
        if self.block_trade_detected:
            parts.append("block trade")
        return " + ".join(parts) if parts else "Normal activity"
