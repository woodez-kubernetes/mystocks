from django.db import models


SIGNAL_CHOICES = [
    ('buy', 'Buy'),
    ('hold', 'Hold'),
    ('sell', 'Sell'),
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
