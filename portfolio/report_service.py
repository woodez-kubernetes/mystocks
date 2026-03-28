import io
import logging
from django.utils import timezone
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string

from analysis.models import AIAnalysis, IndicatorSnapshot
from portfolio.models import Portfolio, ReportAuditLog, WatchlistItem

logger = logging.getLogger(__name__)


class ReportChartService:
    """Generates matplotlib charts for email embedding."""

    BG_COLOR = '#1a1a2e'
    TEXT_COLOR = '#e0e0e0'
    GRID_COLOR = '#333355'
    GAIN_COLOR = '#00c853'
    LOSS_COLOR = '#ff1744'

    @classmethod
    def _apply_dark_style(cls, fig, ax):
        fig.patch.set_facecolor(cls.BG_COLOR)
        ax.set_facecolor(cls.BG_COLOR)
        ax.tick_params(colors=cls.TEXT_COLOR, labelsize=8)
        ax.xaxis.label.set_color(cls.TEXT_COLOR)
        ax.yaxis.label.set_color(cls.TEXT_COLOR)
        ax.title.set_color(cls.TEXT_COLOR)
        for spine in ax.spines.values():
            spine.set_color(cls.GRID_COLOR)
        ax.grid(True, alpha=0.3, color=cls.GRID_COLOR)

    @classmethod
    def generate_portfolio_allocation_chart(cls, holdings):
        """Pie chart of portfolio allocation by current value."""
        labels = []
        sizes = []
        for h in holdings:
            if h.get('current_value') and h['current_value'] > 0:
                labels.append(h['ticker'].symbol)
                sizes.append(float(h['current_value']))

        if not sizes:
            return None

        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        fig.patch.set_facecolor(cls.BG_COLOR)
        colors = plt.cm.Set3(range(len(labels)))
        ax.pie(
            sizes, labels=labels, autopct='%1.1f%%',
            colors=colors, textprops={'color': cls.TEXT_COLOR, 'fontsize': 8},
        )
        ax.set_title('Allocation', color=cls.TEXT_COLOR, fontsize=10, fontweight='bold')
        plt.tight_layout()
        return cls._fig_to_bytes(fig)

    @classmethod
    def generate_top_picks_chart(cls, top_picks):
        """Horizontal bar chart of opportunity scores for top 5 picks."""
        symbols = []
        scores = []
        for pick in top_picks:
            symbols.append(pick['ticker'].symbol)
            scores.append(pick['indicators'].opportunity_score)

        if not scores:
            return None

        fig, ax = plt.subplots(figsize=(5, max(2, len(symbols) * 0.5)), dpi=100)
        cls._apply_dark_style(fig, ax)

        colors = []
        for s in scores:
            if s >= 70:
                colors.append(cls.GAIN_COLOR)
            elif s >= 40:
                colors.append('#ffd740')
            else:
                colors.append(cls.LOSS_COLOR)

        ax.barh(symbols, scores, color=colors, edgecolor='none')
        ax.set_xlim(0, 100)
        ax.set_xlabel('Score')
        ax.set_title('Top 5 Best Buys', fontsize=10, fontweight='bold')
        plt.tight_layout()
        return cls._fig_to_bytes(fig)

    @staticmethod
    def _fig_to_bytes(fig):
        buf = io.BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight',
                    facecolor=fig.get_facecolor(), edgecolor='none')
        plt.close(fig)
        buf.seek(0)
        return buf.read()


class EmailReportService:
    """Assembles and sends the portfolio email report."""

    @staticmethod
    def get_top_picks(user, limit=5):
        """Return the top N tickers by opportunity score for a given user."""
        ticker_ids = set()

        for portfolio in user.portfolios.prefetch_related('lots__ticker').all():
            for lot in portfolio.lots.all():
                ticker_ids.add(lot.ticker_id)

        for item in user.watchlist_items.select_related('ticker').all():
            ticker_ids.add(item.ticker_id)

        if not ticker_ids:
            return []

        snapshots = (
            IndicatorSnapshot.objects
            .filter(ticker_id__in=ticker_ids)
            .select_related('ticker')
            .order_by('-opportunity_score')[:limit]
        )

        picks = []
        for snap in snapshots:
            try:
                ai_analysis = snap.ticker.ai_analysis
            except AIAnalysis.DoesNotExist:
                ai_analysis = None

            picks.append({
                'ticker': snap.ticker,
                'indicators': snap,
                'ai_analysis': ai_analysis,
            })

        return picks

    @staticmethod
    def gather_report_data(user):
        portfolios = user.portfolios.prefetch_related('lots__ticker').all()
        report_portfolios = []

        for portfolio in portfolios:
            holdings = portfolio.get_holdings()
            report_portfolios.append({
                'portfolio': portfolio,
                'holdings': holdings,
            })

        top_picks = EmailReportService.get_top_picks(user)

        return {
            'portfolios': report_portfolios,
            'top_picks': top_picks,
            'generated_at': timezone.localtime(timezone.now()),
        }

    @staticmethod
    def refresh_portfolio_data(user):
        """Refresh quotes, indicators, news, and AI analysis for a user's tickers."""
        import time
        from market.services import StockDataService
        from analysis.services import AIAnalysisService

        tickers = set()
        for portfolio in user.portfolios.prefetch_related('lots__ticker').all():
            for lot in portfolio.lots.all():
                tickers.add(lot.ticker)

        for item in user.watchlist_items.select_related('ticker').all():
            tickers.add(item.ticker)

        for ticker in tickers:
            try:
                StockDataService.refresh_ticker(ticker)
            except Exception:
                logger.exception(f"Report refresh: failed to refresh {ticker.symbol}")
            try:
                AIAnalysisService.generate_analysis(ticker)
            except Exception:
                logger.exception(f"Report refresh: failed AI analysis for {ticker.symbol}")
            time.sleep(0.5)

        logger.info(f"Report data refresh complete for {len(tickers)} tickers")

    @staticmethod
    def generate_and_send(user):
        EmailReportService.refresh_portfolio_data(user)
        data = EmailReportService.gather_report_data(user)

        recipient = settings.REPORT_RECIPIENT_EMAIL
        if not recipient:
            raise ValueError(
                'REPORT_RECIPIENT_EMAIL is not configured. '
                'Set it in your environment variables.'
            )

        portfolio_count = len(data['portfolios'])
        ticker_count = sum(
            len(pdata['holdings']) for pdata in data['portfolios']
        )

        try:
            images = {}

            for pdata in data['portfolios']:
                portfolio = pdata['portfolio']
                holdings = pdata['holdings']
                prefix = f'p{portfolio.pk}'

                alloc_bytes = ReportChartService.generate_portfolio_allocation_chart(holdings)
                if alloc_bytes:
                    cid = f'{prefix}_allocation'
                    images[cid] = alloc_bytes
                    pdata['allocation_chart_cid'] = cid

            if data['top_picks']:
                picks_bytes = ReportChartService.generate_top_picks_chart(data['top_picks'])
                if picks_bytes:
                    images['top_picks'] = picks_bytes
                    data['top_picks_chart_cid'] = 'top_picks'

            html_content = render_to_string('portfolio/email_report.html', data)

            generated = data['generated_at']
            subject = f'ApexKube Capital \u2014 Weekly Report \u2014 {generated.strftime("%B %d, %Y")}'
            text_content = 'Your weekly portfolio report. Please view in an HTML-capable email client.'
            from_email = settings.DEFAULT_FROM_EMAIL

            # Build multipart/related MIME message manually
            # (Django 6.0 removed mixed_subtype support)
            msg_root = MIMEMultipart('related')
            msg_root['Subject'] = subject
            msg_root['From'] = from_email
            msg_root['To'] = recipient

            # multipart/alternative for text + HTML
            msg_alt = MIMEMultipart('alternative')
            msg_alt.attach(MIMEText(text_content, 'plain'))
            msg_alt.attach(MIMEText(html_content, 'html'))
            msg_root.attach(msg_alt)

            # Attach CID images
            for cid, img_bytes in images.items():
                mime_img = MIMEImage(img_bytes, _subtype='png')
                mime_img.add_header('Content-ID', f'<{cid}>')
                mime_img.add_header('Content-Disposition', 'inline', filename=f'{cid}.png')
                msg_root.attach(mime_img)

            # Send via Django's email backend
            django_msg = EmailMessage(
                subject=subject,
                body='',
                from_email=from_email,
                to=[recipient],
            )
            django_msg.encoding = 'utf-8'
            connection = django_msg.get_connection()
            connection.open()
            connection.connection.sendmail(
                from_email, [recipient], msg_root.as_string()
            )
            connection.close()

            ReportAuditLog.objects.create(
                recipient=recipient,
                status='success',
                ticker_count=ticker_count,
                portfolio_count=portfolio_count,
            )

            logger.info(f'Portfolio report sent to {recipient}')
            return True

        except Exception as e:
            ReportAuditLog.objects.create(
                recipient=recipient,
                status='error',
                error_message=str(e),
                ticker_count=ticker_count,
                portfolio_count=portfolio_count,
            )
            raise
