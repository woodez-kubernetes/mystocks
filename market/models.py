from django.db import models

from portfolio.models import Ticker


class PriceHistory(models.Model):
    ticker = models.ForeignKey(
        Ticker, on_delete=models.CASCADE, related_name='price_history'
    )
    date = models.DateField()
    open = models.DecimalField(max_digits=12, decimal_places=2)
    high = models.DecimalField(max_digits=12, decimal_places=2)
    low = models.DecimalField(max_digits=12, decimal_places=2)
    close = models.DecimalField(max_digits=12, decimal_places=2)
    volume = models.BigIntegerField()

    class Meta:
        unique_together = ('ticker', 'date')
        ordering = ['-date']

    def __str__(self):
        return f"{self.ticker.symbol} {self.date} close={self.close}"


class QuarterlyEarning(models.Model):
    ticker = models.ForeignKey(
        Ticker, on_delete=models.CASCADE, related_name='quarterly_earnings'
    )
    period_end_date = models.DateField()
    fiscal_period = models.CharField(max_length=10)
    eps_actual = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    growth_qoq_pct = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        unique_together = ('ticker', 'period_end_date')
        ordering = ['-period_end_date']

    def __str__(self):
        return f"{self.ticker.symbol} {self.fiscal_period} eps={self.eps_actual}"


SENTIMENT_CHOICES = [
    ('positive', 'Positive'),
    ('neutral', 'Neutral'),
    ('negative', 'Negative'),
]

FEED_CATEGORY_CHOICES = [
    ('stock', 'Stock/Market'),
    ('geopolitical', 'Geopolitical'),
]


class RSSFeedSource(models.Model):
    name = models.CharField(max_length=200)
    url = models.URLField(max_length=500, unique=True)
    category = models.CharField(
        max_length=15, choices=FEED_CATEGORY_CHOICES, default='stock'
    )
    enabled = models.BooleanField(default=True)
    last_fetched = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.category})"


class NewsArticle(models.Model):
    ticker = models.ForeignKey(
        Ticker, on_delete=models.CASCADE, related_name='news_articles',
        null=True, blank=True,
    )
    feed_source = models.ForeignKey(
        RSSFeedSource, on_delete=models.SET_NULL, related_name='articles',
        null=True, blank=True,
    )
    title = models.CharField(max_length=500)
    url = models.URLField(max_length=1000, unique=True)
    source = models.CharField(max_length=200, blank=True)
    published_at = models.DateTimeField()
    fetched_at = models.DateTimeField(auto_now_add=True)
    sentiment_score = models.DecimalField(
        max_digits=4, decimal_places=3, null=True, blank=True
    )
    sentiment_label = models.CharField(
        max_length=8, choices=SENTIMENT_CHOICES, default='neutral'
    )

    class Meta:
        ordering = ['-published_at']

    def __str__(self):
        symbol = self.ticker.symbol if self.ticker else 'General'
        return f"{symbol}: {self.title[:60]}"
