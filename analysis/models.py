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

    def __str__(self):
        return f'{self.ticker.symbol} score={self.opportunity_score}'

    @property
    def signal_summary(self):
        """Return list of (label, signal) tuples for all indicators."""
        return [
            ('RSI', self.rsi_signal),
            ('MACD', self.macd_signal),
            ('BB', self.bb_signal),
            ('SMA', self.sma_signal),
            ('Vol', self.volume_signal),
            ('Sent', self.sentiment_signal),
        ]

    class Meta:
        ordering = ['-opportunity_score']


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
