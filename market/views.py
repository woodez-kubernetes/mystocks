import json

from django.db import models
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, render

from market.models import NewsArticle, PriceHistory, RSSFeedSource
from market.services import NewsService, StockDataService
from portfolio.models import Lot, Ticker


def ticker_detail(request, symbol):
    symbol = symbol.upper()
    ticker = get_object_or_404(Ticker, symbol=symbol)

    # Get holdings for current user's portfolios
    lots = Lot.objects.filter(
        ticker=ticker, portfolio__user=request.user
    ).select_related('portfolio')
    total_shares = sum(lot.shares for lot in lots)

    # Recent price history for initial chart (3 months)
    prices = PriceHistory.objects.filter(ticker=ticker).order_by('date')[:90]
    chart_labels = [p.date.isoformat() for p in prices]
    chart_prices = [float(p.close) for p in prices]

    # Technical indicators
    try:
        indicators = ticker.indicators
    except Exception:
        indicators = None

    # AI Analysis
    try:
        ai_analysis = ticker.ai_analysis
    except Exception:
        ai_analysis = None

    # Options data
    try:
        options_snapshot = ticker.options_snapshot
    except Exception:
        options_snapshot = None

    # News articles
    news_articles = NewsArticle.objects.filter(ticker=ticker)[:10]
    aggregate_sentiment = NewsService.get_aggregate_sentiment(ticker)

    # Recent SEC filings (insider transactions)
    from analysis.models import SECFiling, WhaleActivity
    recent_filings = SECFiling.objects.filter(
        ticker=ticker, form_type='4',
    ).order_by('-filed_at')[:2]
    whale = WhaleActivity.objects.filter(ticker=ticker).order_by('-date').first()

    context = {
        'ticker': ticker,
        'lots': lots,
        'total_shares': total_shares,
        'chart_labels': json.dumps(chart_labels),
        'chart_prices': json.dumps(chart_prices),
        'indicators': indicators,
        'ai_analysis': ai_analysis,
        'options_snapshot': options_snapshot,
        'news_articles': news_articles,
        'aggregate_sentiment': aggregate_sentiment,
        'recent_filings': recent_filings,
        'whale': whale,
    }
    return render(request, 'market/ticker_detail.html', context)


def chart_data(request, symbol):
    """JSON API for chart data with dynamic period."""
    symbol = symbol.upper()
    ticker = get_object_or_404(Ticker, symbol=symbol)
    period = request.GET.get('period', '3mo')

    # Map period to approximate day count for DB query
    period_days = {
        '5d': 5,
        '1mo': 30,
        '3mo': 90,
        '6mo': 180,
        '1y': 365,
        '2y': 730,
        '5y': 1825,
    }
    days = period_days.get(period, 90)
    prices = PriceHistory.objects.filter(ticker=ticker).order_by('date')

    # If we don't have enough cached data for this period, fetch from yfinance
    if prices.count() < days * 0.5:
        history = StockDataService.get_history(symbol, period=period)
        labels = [rec['date'].isoformat() for rec in history if rec['close']]
        values = [float(rec['close']) for rec in history if rec['close']]
    else:
        recent = list(prices)[-days:] if days < prices.count() else list(prices)
        labels = [p.date.isoformat() for p in recent]
        values = [float(p.close) for p in recent]

    result = {'labels': labels, 'prices': values}

    # Optional indicator overlays
    indicators = request.GET.get('indicators', '')
    if indicators and len(values) >= 20:
        import pandas as pd
        from ta.trend import SMAIndicator
        from ta.volatility import BollingerBands

        close_series = pd.Series(values, dtype=float)
        requested = [i.strip() for i in indicators.split(',')]

        if 'sma50' in requested and len(values) >= 50:
            sma = SMAIndicator(close=close_series, window=50).sma_indicator()
            result['sma50'] = [round(v, 2) if not pd.isna(v) else None for v in sma]
        if 'sma200' in requested and len(values) >= 200:
            sma = SMAIndicator(close=close_series, window=200).sma_indicator()
            result['sma200'] = [round(v, 2) if not pd.isna(v) else None for v in sma]
        if 'bb' in requested and len(values) >= 20:
            bb = BollingerBands(close=close_series, window=20, window_dev=2)
            result['bb_upper'] = [round(v, 2) if not pd.isna(v) else None for v in bb.bollinger_hband()]
            result['bb_lower'] = [round(v, 2) if not pd.isna(v) else None for v in bb.bollinger_lband()]

    return JsonResponse(result)


def settings_view(request):
    """Settings page with RSS feed management and report schedules."""
    from portfolio.forms import ReportScheduleForm
    feeds = RSSFeedSource.objects.all()
    schedules = request.user.report_schedules.all()
    return render(request, 'market/settings.html', {
        'feeds': feeds,
        'schedules': schedules,
        'form': ReportScheduleForm(),
    })


def toggle_feed_view(request, pk):
    """Toggle an RSS feed source enabled/disabled."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    feed = get_object_or_404(RSSFeedSource, pk=pk)
    feed.enabled = not feed.enabled
    feed.save(update_fields=['enabled'])

    if request.headers.get('HX-Request'):
        feeds = RSSFeedSource.objects.all()
        return render(request, 'market/partials/feed_list.html', {'feeds': feeds})

    return JsonResponse({'success': True, 'enabled': feed.enabled})


def news_feed_view(request):
    """Top-level news page showing articles from all sources."""
    category = request.GET.get('category', 'all')

    articles = NewsArticle.objects.select_related('ticker', 'feed_source')

    if category == 'stock':
        articles = articles.filter(
            models.Q(feed_source__category='stock') | models.Q(feed_source__isnull=True)
        )
    elif category == 'geopolitical':
        articles = articles.filter(feed_source__category='geopolitical')
    elif category == 'ticker':
        articles = articles.filter(ticker__isnull=False, feed_source__isnull=True)

    articles = articles.order_by('-published_at')[:100]

    context = {
        'articles': articles,
        'category': category,
    }
    return render(request, 'market/news_page.html', context)


def refresh_ticker_view(request, symbol):
    """Refresh a single ticker's data (HTMX endpoint)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    symbol = symbol.upper()
    ticker = get_object_or_404(Ticker, symbol=symbol)

    try:
        StockDataService.refresh_ticker(ticker)
        ticker.refresh_from_db()
        data = {
            'success': True,
            'price': str(ticker.last_price) if ticker.last_price else None,
            'day_change': str(ticker.day_change) if ticker.day_change else None,
            'day_change_pct': str(ticker.day_change_pct) if ticker.day_change_pct else None,
        }
    except Exception as e:
        data = {'success': False, 'error': str(e)}

    if request.headers.get('HX-Request'):
        # Return updated ticker detail header partial
        return render(request, 'market/partials/ticker_header.html', {'ticker': ticker})

    return JsonResponse(data)


def refresh_all_view(request):
    """Refresh all tickers in portfolios."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    results = StockDataService.refresh_all(sleep_between=0.5)
    success_count = sum(1 for _, ok in results if ok)
    fail_count = sum(1 for _, ok in results if not ok)

    if request.headers.get('HX-Request'):
        from django.contrib import messages
        if fail_count:
            messages.warning(request, f'Refreshed {success_count} tickers, {fail_count} failed.')
        else:
            messages.success(request, f'Refreshed {success_count} tickers.')
        from django.http import HttpResponse
        response = HttpResponse('')
        response['HX-Refresh'] = 'true'
        return response

    return JsonResponse({
        'success': True,
        'refreshed': success_count,
        'failed': fail_count,
    })


def generate_ai_analysis_view(request, symbol):
    """HTMX endpoint: generate AI analysis on demand."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    symbol = symbol.upper()
    ticker = get_object_or_404(Ticker, symbol=symbol)

    from analysis.services import AIAnalysisService
    ai_analysis = AIAnalysisService.generate_analysis(ticker, force=True)

    return render(request, 'analysis/partials/ai_analysis_card.html', {
        'ai_analysis': ai_analysis,
        'ticker': ticker,
    })
