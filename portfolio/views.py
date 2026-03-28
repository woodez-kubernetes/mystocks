import csv

from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from analysis.models import IndicatorSnapshot
from .forms import LotForm, PortfolioForm, ReportScheduleForm
from .models import Lot, Portfolio, ReportAuditLog, ReportSchedule, Ticker


def dashboard(request):
    portfolios = Portfolio.objects.prefetch_related('lots__ticker').all()
    context = {
        'portfolios': portfolios,
        'portfolio_count': portfolios.count(),
        'ticker_count': Ticker.objects.filter(lots__isnull=False).distinct().count(),
        'lot_count': Lot.objects.count(),
    }
    return render(request, 'portfolio/dashboard.html', context)


def metrics_info(request):
    return render(request, 'portfolio/metrics_info.html')


# --- Portfolio CRUD ---

def portfolio_list(request):
    portfolios = Portfolio.objects.prefetch_related('lots__ticker').all()
    return render(request, 'portfolio/portfolio_list.html', {'portfolios': portfolios})


def portfolio_detail(request, pk):
    portfolio = get_object_or_404(Portfolio, pk=pk)
    holdings = portfolio.get_holdings()

    # Portfolio AI analysis (if previously generated)
    try:
        portfolio_analysis = portfolio.ai_portfolio_analysis
    except Exception:
        portfolio_analysis = None

    context = {
        'portfolio': portfolio,
        'holdings': holdings,
        'portfolio_analysis': portfolio_analysis,
    }
    return render(request, 'portfolio/portfolio_detail.html', context)


def portfolio_create(request):
    if request.method == 'POST':
        form = PortfolioForm(request.POST)
        if form.is_valid():
            portfolio = form.save()
            if request.headers.get('HX-Request'):
                return render(
                    request,
                    'portfolio/partials/portfolio_card.html',
                    {'p': portfolio},
                )
            messages.success(request, f'Portfolio "{portfolio.name}" created.')
            return redirect('portfolio_list')
    else:
        form = PortfolioForm()

    return render(request, 'portfolio/partials/portfolio_form.html', {
        'form': form,
        'title': 'Create Portfolio',
        'action_url': 'portfolio_create',
    })


def portfolio_edit(request, pk):
    portfolio = get_object_or_404(Portfolio, pk=pk)
    if request.method == 'POST':
        form = PortfolioForm(request.POST, instance=portfolio)
        if form.is_valid():
            form.save()
            if request.headers.get('HX-Request'):
                return render(
                    request,
                    'portfolio/partials/portfolio_card.html',
                    {'p': portfolio},
                )
            messages.success(request, f'Portfolio "{portfolio.name}" updated.')
            return redirect('portfolio_detail', pk=portfolio.pk)
    else:
        form = PortfolioForm(instance=portfolio)

    return render(request, 'portfolio/partials/portfolio_form.html', {
        'form': form,
        'title': 'Edit Portfolio',
        'action_url': 'portfolio_edit',
        'action_url_pk': portfolio.pk,
        'portfolio': portfolio,
    })


def portfolio_delete(request, pk):
    portfolio = get_object_or_404(Portfolio, pk=pk)
    if request.method == 'POST':
        name = portfolio.name
        portfolio.delete()
        if request.headers.get('HX-Request'):
            from django.http import HttpResponse
            response = HttpResponse('')
            response['HX-Redirect'] = '/portfolios/'
            return response
        messages.success(request, f'Portfolio "{name}" deleted.')
        return redirect('portfolio_list')

    return render(request, 'portfolio/partials/confirm_delete.html', {
        'object': portfolio,
        'object_type': 'portfolio',
        'delete_url': 'portfolio_delete',
        'delete_url_pk': portfolio.pk,
    })


# --- Lot CRUD ---

def lot_create(request, portfolio_pk):
    portfolio = get_object_or_404(Portfolio, pk=portfolio_pk)
    if request.method == 'POST':
        form = LotForm(request.POST, portfolio=portfolio)
        if form.is_valid():
            form.save()
            if request.headers.get('HX-Request'):
                holdings = portfolio.get_holdings()
                return render(request, 'portfolio/partials/holdings_table.html', {
                    'portfolio': portfolio,
                    'holdings': holdings,
                })
            messages.success(request, 'Lot added successfully.')
            return redirect('portfolio_detail', pk=portfolio.pk)
    else:
        form = LotForm(portfolio=portfolio)

    tickers = list(Ticker.objects.values_list('symbol', flat=True))
    return render(request, 'portfolio/partials/lot_form.html', {
        'form': form,
        'portfolio': portfolio,
        'title': 'Add Lot',
        'tickers': tickers,
    })


def lot_edit(request, pk):
    lot = get_object_or_404(Lot.objects.select_related('portfolio', 'ticker'), pk=pk)
    portfolio = lot.portfolio
    if request.method == 'POST':
        form = LotForm(request.POST, instance=lot, portfolio=portfolio)
        if form.is_valid():
            form.save()
            if request.headers.get('HX-Request'):
                holdings = portfolio.get_holdings()
                return render(request, 'portfolio/partials/holdings_table.html', {
                    'portfolio': portfolio,
                    'holdings': holdings,
                })
            messages.success(request, 'Lot updated.')
            return redirect('portfolio_detail', pk=portfolio.pk)
    else:
        form = LotForm(instance=lot, portfolio=portfolio)

    tickers = list(Ticker.objects.values_list('symbol', flat=True))
    return render(request, 'portfolio/partials/lot_form.html', {
        'form': form,
        'portfolio': portfolio,
        'title': 'Edit Lot',
        'lot': lot,
        'tickers': tickers,
    })


def lot_delete(request, pk):
    lot = get_object_or_404(Lot.objects.select_related('portfolio'), pk=pk)
    portfolio = lot.portfolio
    if request.method == 'POST':
        lot.delete()
        if request.headers.get('HX-Request'):
            holdings = portfolio.get_holdings()
            return render(request, 'portfolio/partials/holdings_table.html', {
                'portfolio': portfolio,
                'holdings': holdings,
            })
        messages.success(request, 'Lot deleted.')
        return redirect('portfolio_detail', pk=portfolio.pk)

    return render(request, 'portfolio/partials/confirm_delete.html', {
        'object': lot,
        'object_type': 'lot',
        'delete_url': 'lot_delete',
        'delete_url_pk': lot.pk,
        'portfolio': portfolio,
    })


# --- CSV Export ---

def portfolio_export_csv(request, pk):
    """Download portfolio holdings as a CSV file."""
    portfolio = get_object_or_404(Portfolio, pk=pk)
    holdings = portfolio.get_holdings()

    safe_name = portfolio.name.replace(' ', '_').replace('"', '')
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{safe_name}_holdings.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Ticker', 'Company Name', 'Sector', 'Shares', 'Cost Basis',
        'Purchase Date', 'Notes', 'Current Price', 'Day Change %',
        'Current Value', 'Gain/Loss ($)', 'Gain/Loss (%)', 'Opportunity Score',
    ])

    for h in holdings:
        ticker = h['ticker']
        try:
            score = ticker.indicators.opportunity_score
        except IndicatorSnapshot.DoesNotExist:
            score = ''

        # Ticker summary row
        writer.writerow([
            ticker.symbol,
            ticker.company_name,
            ticker.sector,
            h['total_shares'],
            h['avg_cost'],
            '',
            '',
            ticker.last_price or '',
            ticker.day_change_pct or '',
            h['current_value'] or '',
            h['gain_loss'] or '',
            f"{h['gain_loss_pct']:.1f}" if h.get('gain_loss_pct') is not None else '',
            score,
        ])

        # Lot detail rows
        for lot in h['lots']:
            writer.writerow([
                '  ↳',
                '',
                '',
                lot.shares,
                lot.cost_basis,
                lot.purchase_date,
                lot.notes,
                '',
                '',
                lot.current_value or '',
                lot.gain_loss or '',
                f"{lot.gain_loss_pct:.1f}" if lot.gain_loss_pct is not None else '',
                '',
            ])

    return response


# --- Portfolio AI Analysis ---

@require_POST
def generate_portfolio_analysis(request, pk):
    """HTMX endpoint: generate portfolio-level AI analysis on demand."""
    portfolio = get_object_or_404(Portfolio, pk=pk)

    from analysis.services import PortfolioAnalysisService
    portfolio_analysis = PortfolioAnalysisService.generate_analysis(portfolio, force=True)

    return render(request, 'portfolio/partials/portfolio_analysis_section.html', {
        'portfolio': portfolio,
        'portfolio_analysis': portfolio_analysis,
    })


# --- Portfolio Growth Chart API ---

def portfolio_growth_data(request, pk):
    """JSON API: 52-week portfolio growth vs major indices (% return)."""
    import yfinance as yf

    portfolio = get_object_or_404(Portfolio, pk=pk)
    holdings = portfolio.get_holdings()

    if not holdings:
        return JsonResponse({'labels': [], 'portfolio': [], 'indices': {}})

    # Build {symbol: total_shares} map
    ticker_shares = {}
    for h in holdings:
        ticker_shares[h['ticker'].symbol] = float(h['total_shares'])

    # Fetch 1Y history for each holding
    symbols = list(ticker_shares.keys())
    all_histories = {}
    for symbol in symbols:
        try:
            stock = yf.Ticker(symbol)
            df = stock.history(period='1y')
            if not df.empty:
                all_histories[symbol] = df['Close']
        except Exception:
            pass

    if not all_histories:
        return JsonResponse({'labels': [], 'portfolio': [], 'indices': {}})

    # Build a common date index from all histories
    import pandas as pd
    combined = pd.DataFrame(all_histories)
    combined = combined.dropna(how='all').ffill()

    # Calculate daily portfolio value
    daily_value = pd.Series(0.0, index=combined.index)
    for symbol, shares in ticker_shares.items():
        if symbol in combined.columns:
            daily_value += combined[symbol].fillna(0) * shares

    # Normalize to % return from first valid day
    first_val = daily_value.iloc[0]
    if first_val and first_val > 0:
        portfolio_pct = ((daily_value / first_val) - 1) * 100
    else:
        portfolio_pct = daily_value * 0

    # Fetch major indices
    index_symbols = {
        '^GSPC': 'S&P 500',
        '^IXIC': 'NASDAQ',
        '^DJI': 'Dow Jones',
    }
    indices_data = {}
    for idx_symbol, idx_name in index_symbols.items():
        try:
            idx = yf.Ticker(idx_symbol)
            df = idx.history(period='1y')
            if not df.empty:
                close = df['Close'].reindex(combined.index, method='ffill').dropna()
                if len(close) > 0:
                    first = close.iloc[0]
                    indices_data[idx_name] = [
                        round(((v / first) - 1) * 100, 2) for v in close
                    ]
        except Exception:
            pass

    labels = [d.strftime('%Y-%m-%d') for d in combined.index]
    portfolio_values = [round(v, 2) for v in portfolio_pct]

    return JsonResponse({
        'labels': labels,
        'portfolio': portfolio_values,
        'indices': indices_data,
    })


# --- Ticker Search API ---

def ticker_search(request):
    q = request.GET.get('q', '').strip()
    if len(q) < 1:
        return JsonResponse([], safe=False)
    tickers = Ticker.objects.filter(symbol__istartswith=q)[:10]
    results = [
        {'symbol': t.symbol, 'name': t.company_name}
        for t in tickers
    ]
    return JsonResponse(results, safe=False)


# --- Report Schedules ---

def _render_schedule_list(request):
    schedules = ReportSchedule.objects.all()
    return render(request, 'portfolio/partials/schedule_list.html', {
        'schedules': schedules,
        'form': ReportScheduleForm(),
    })


@require_POST
def schedule_create(request):
    form = ReportScheduleForm(request.POST)
    if form.is_valid():
        form.save()
        if request.headers.get('HX-Request'):
            return _render_schedule_list(request)
        return redirect('settings')
    if request.headers.get('HX-Request'):
        schedules = ReportSchedule.objects.all()
        return render(request, 'portfolio/partials/schedule_list.html', {
            'schedules': schedules,
            'form': form,
        })
    return redirect('settings')


@require_POST
def schedule_edit(request, pk):
    schedule = get_object_or_404(ReportSchedule, pk=pk)
    form = ReportScheduleForm(request.POST, instance=schedule)
    if form.is_valid():
        form.save()
    if request.headers.get('HX-Request'):
        return _render_schedule_list(request)
    return redirect('settings')


@require_POST
def schedule_delete(request, pk):
    schedule = get_object_or_404(ReportSchedule, pk=pk)
    schedule.delete()
    if request.headers.get('HX-Request'):
        return _render_schedule_list(request)
    return redirect('settings')


@require_POST
def schedule_toggle(request, pk):
    schedule = get_object_or_404(ReportSchedule, pk=pk)
    schedule.enabled = not schedule.enabled
    schedule.save(update_fields=['enabled'])
    if request.headers.get('HX-Request'):
        return _render_schedule_list(request)
    return redirect('settings')


# --- Audit Log ---

def report_audit_log(request):
    logs = ReportAuditLog.objects.all()[:50]
    return render(request, 'portfolio/audit_log.html', {'logs': logs})


# --- Email Report ---

@require_POST
def send_email_report(request):
    """Send portfolio email report via Gmail SMTP."""
    from portfolio.report_service import EmailReportService

    try:
        EmailReportService.generate_and_send()
        if request.headers.get('HX-Request'):
            return HttpResponse(
                '<div class="alert alert-success alert-dismissible fade show" role="alert">'
                '<i class="bi bi-check-circle me-2"></i>Report sent successfully!'
                '<button type="button" class="btn-close" data-bs-dismiss="alert"></button>'
                '</div>'
            )
        messages.success(request, 'Portfolio report sent successfully!')
        return redirect('dashboard')
    except Exception as e:
        if request.headers.get('HX-Request'):
            return HttpResponse(
                f'<div class="alert alert-danger alert-dismissible fade show" role="alert">'
                f'<i class="bi bi-exclamation-triangle me-2"></i>Failed to send report: {e}'
                f'<button type="button" class="btn-close" data-bs-dismiss="alert"></button>'
                f'</div>',
                status=500,
            )
        messages.error(request, f'Failed to send report: {e}')
        return redirect('dashboard')
