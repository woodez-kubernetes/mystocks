from django.contrib import admin

from .models import NewsArticle, PriceHistory, RSSFeedSource


@admin.register(PriceHistory)
class PriceHistoryAdmin(admin.ModelAdmin):
    list_display = ('ticker', 'date', 'open', 'high', 'low', 'close', 'volume')
    list_filter = ('ticker',)
    ordering = ('-date',)


@admin.register(NewsArticle)
class NewsArticleAdmin(admin.ModelAdmin):
    list_display = ('ticker', 'title', 'source', 'feed_source', 'sentiment_label', 'sentiment_score', 'published_at')
    list_filter = ('sentiment_label', 'ticker', 'feed_source')
    ordering = ('-published_at',)


@admin.register(RSSFeedSource)
class RSSFeedSourceAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'enabled', 'last_fetched')
    list_filter = ('category', 'enabled')
