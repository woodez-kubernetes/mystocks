from decimal import Decimal

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from analysis.models import IndicatorSnapshot, OptionsSnapshot
from portfolio.models import Ticker, WatchlistItem


def opportunities_view(request):
    """Buying opportunities dashboard ranked by opportunity score."""
    snapshots = IndicatorSnapshot.objects.select_related('ticker').all()

    # Filters
    signal_filter = request.GET.get('signal', '')
    sector_filter = request.GET.get('sector', '')
    sort_by = request.GET.get('sort', 'score')

    if signal_filter in ('buy', 'hold', 'sell'):
        # Filter tickers where majority of signals match
        snapshot_ids = []
        for s in snapshots:
            signals = [s.rsi_signal, s.macd_signal, s.bb_signal,
                        s.sma_signal, s.volume_signal, s.sentiment_signal]
            count = signals.count(signal_filter)
            if count >= 2:  # at least 2 indicators agree
                snapshot_ids.append(s.pk)
        snapshots = snapshots.filter(pk__in=snapshot_ids)

    if sector_filter:
        snapshots = snapshots.filter(ticker__sector=sector_filter)

    # Sorting
    if sort_by == 'name':
        snapshots = snapshots.order_by('ticker__symbol')
    elif sort_by == 'change':
        snapshots = snapshots.order_by('-ticker__day_change_pct')
    else:  # default: score
        snapshots = snapshots.order_by('-opportunity_score')

    # Summary stats
    all_snapshots = list(snapshots)
    total = len(all_snapshots)
    buy_count = sum(1 for s in all_snapshots if s.opportunity_score >= 70)
    hold_count = sum(1 for s in all_snapshots if 40 <= s.opportunity_score < 70)
    sell_count = sum(1 for s in all_snapshots if s.opportunity_score < 40)
    avg_score = (
        sum(s.opportunity_score for s in all_snapshots) / total
        if total > 0 else 0
    )

    # Sectors for filter dropdown
    sectors = (
        Ticker.objects.exclude(sector='')
        .values_list('sector', flat=True)
        .distinct()
        .order_by('sector')
    )

    # Portfolios for quick-add
    from portfolio.models import Portfolio
    portfolios = Portfolio.objects.all()

    context = {
        'snapshots': snapshots,
        'sectors': sectors,
        'portfolios': portfolios,
        'signal_filter': signal_filter,
        'sector_filter': sector_filter,
        'sort_by': sort_by,
        'total': total,
        'buy_count': buy_count,
        'hold_count': hold_count,
        'sell_count': sell_count,
        'avg_score': round(avg_score, 1),
    }
    return render(request, 'analysis/opportunities.html', context)


def ticker_radar_data(request, symbol):
    """JSON API returning sub-scores for a ticker's radar chart."""
    symbol = symbol.upper()
    ticker = get_object_or_404(Ticker, symbol=symbol)
    try:
        snap = ticker.indicators
    except IndicatorSnapshot.DoesNotExist:
        return JsonResponse({'labels': [], 'scores': []})

    # Compute sub-scores (same logic as _compute_score but return individual scores)
    import pandas as pd
    scores = {}

    # RSI sub-score
    if snap.rsi is not None:
        scores['RSI'] = max(0, min(100, 100 - float(snap.rsi)))
    else:
        scores['RSI'] = 50

    # MACD sub-score
    if snap.macd_histogram is not None and ticker.last_price and ticker.last_price > 0:
        norm = (float(snap.macd_histogram) / float(ticker.last_price)) * 1000
        scores['MACD'] = max(0, min(100, 50 + norm * 10))
    else:
        scores['MACD'] = 50

    # BB sub-score
    if all(v is not None for v in [snap.bb_lower, snap.bb_upper]) and ticker.last_price:
        bb_range = float(snap.bb_upper) - float(snap.bb_lower)
        if bb_range > 0:
            position = (float(ticker.last_price) - float(snap.bb_lower)) / bb_range
            scores['Bollinger'] = max(0, min(100, (1 - position) * 100))
        else:
            scores['Bollinger'] = 50
    else:
        scores['Bollinger'] = 50

    # SMA sub-score
    if snap.sma_50 is not None and ticker.last_price:
        sma_score = 50
        if float(ticker.last_price) > float(snap.sma_50):
            sma_score += 15
        else:
            sma_score -= 15
        if snap.sma_200 is not None:
            if float(snap.sma_50) > float(snap.sma_200):
                sma_score += 20
            else:
                sma_score -= 20
        scores['SMA'] = max(0, min(100, sma_score))
    else:
        scores['SMA'] = 50

    # Volume sub-score
    if snap.volume_ratio is not None:
        scores['Volume'] = max(0, min(100, float(snap.volume_ratio) * 40 + 20))
    else:
        scores['Volume'] = 50

    # Sentiment sub-score
    if snap.sentiment_score is not None:
        scores['Sentiment'] = max(0, min(100, (float(snap.sentiment_score) + 1) * 50))
    else:
        scores['Sentiment'] = 50

    # Options sub-score
    try:
        from analysis.models import OptionsSnapshot
        opts = ticker.options_snapshot
        if opts and opts.options_score is not None:
            scores['Options'] = float(opts.options_score)
    except OptionsSnapshot.DoesNotExist:
        pass

    labels = list(scores.keys())
    values = [round(v, 1) for v in scores.values()]

    return JsonResponse({
        'labels': labels,
        'scores': values,
        'overall': snap.opportunity_score,
    })


def watchlist_view(request):
    """Watchlist page showing tracked tickers."""
    items = WatchlistItem.objects.select_related('ticker').all()
    # Attach indicators
    for item in items:
        try:
            item.indicators = item.ticker.indicators
        except IndicatorSnapshot.DoesNotExist:
            item.indicators = None

    return render(request, 'analysis/watchlist.html', {'items': items})


def watchlist_add(request):
    """Add a ticker to the watchlist."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    symbol = request.POST.get('symbol', '').strip().upper()
    if not symbol:
        return JsonResponse({'error': 'Symbol required'}, status=400)

    # Get or create the ticker
    ticker, created = Ticker.objects.get_or_create(symbol=symbol)

    # Check if already on watchlist
    if WatchlistItem.objects.filter(ticker=ticker).exists():
        if request.headers.get('HX-Request'):
            from django.contrib import messages
            messages.info(request, f'{symbol} is already on your watchlist.')
            from django.http import HttpResponse
            response = HttpResponse('')
            response['HX-Refresh'] = 'true'
            return response
        return JsonResponse({'error': 'Already on watchlist'}, status=400)

    notes = request.POST.get('notes', '')
    WatchlistItem.objects.create(ticker=ticker, notes=notes)

    if request.headers.get('HX-Request'):
        from django.contrib import messages
        messages.success(request, f'{symbol} added to watchlist.')
        from django.http import HttpResponse
        response = HttpResponse('')
        response['HX-Refresh'] = 'true'
        return response

    return JsonResponse({'success': True, 'symbol': symbol})


def watchlist_remove(request, pk):
    """Remove a ticker from the watchlist."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    item = get_object_or_404(WatchlistItem, pk=pk)
    symbol = item.ticker.symbol
    item.delete()

    if request.headers.get('HX-Request'):
        from django.contrib import messages
        messages.success(request, f'{symbol} removed from watchlist.')
        from django.http import HttpResponse
        response = HttpResponse('')
        response['HX-Refresh'] = 'true'
        return response

    return JsonResponse({'success': True, 'symbol': symbol})


def compare_view(request):
    """Side-by-side comparison of 2-3 tickers."""
    symbols_param = request.GET.get('symbols', '')
    symbols = [s.strip().upper() for s in symbols_param.split(',') if s.strip()][:3]

    tickers_data = []
    for symbol in symbols:
        try:
            ticker = Ticker.objects.get(symbol=symbol)
            try:
                indicators = ticker.indicators
            except IndicatorSnapshot.DoesNotExist:
                indicators = None
            tickers_data.append({
                'ticker': ticker,
                'indicators': indicators,
            })
        except Ticker.DoesNotExist:
            pass

    # All tickers for the selector
    all_tickers = Ticker.objects.all()

    # Column size: 12/count for equal columns
    col_size = 12 // max(len(tickers_data), 1) if tickers_data else 4

    context = {
        'tickers_data': tickers_data,
        'symbols': symbols,
        'symbols_csv': ','.join(symbols),
        'all_tickers': all_tickers,
        'col_size': col_size,
    }
    return render(request, 'analysis/compare.html', context)
