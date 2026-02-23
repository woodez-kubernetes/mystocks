import io
import logging
from django.utils import timezone
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string

from analysis.models import AIAnalysis, IndicatorSnapshot
from market.models import NewsArticle, PriceHistory
from portfolio.models import Portfolio, ReportAuditLog

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
    def generate_gain_loss_bar_chart(cls, holdings):
        """Horizontal bar chart of gain/loss per holding."""
        symbols = []
        gains = []
        for h in holdings:
            if h.get('gain_loss') is not None:
                symbols.append(h['ticker'].symbol)
                gains.append(float(h['gain_loss']))

        if not gains:
            return None

        fig, ax = plt.subplots(figsize=(5, max(2, len(symbols) * 0.4)), dpi=100)
        cls._apply_dark_style(fig, ax)
        colors = [cls.GAIN_COLOR if g >= 0 else cls.LOSS_COLOR for g in gains]
        ax.barh(symbols, gains, color=colors, edgecolor='none')
        ax.set_xlabel('Gain/Loss ($)')
        ax.set_title('Holdings Gain/Loss', fontsize=10, fontweight='bold')
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'${x:,.0f}'))
        plt.tight_layout()
        return cls._fig_to_bytes(fig)

    @classmethod
    def generate_price_sparkline(cls, ticker, days=90):
        """Small price chart for a single ticker."""
        prices = list(
            PriceHistory.objects.filter(ticker=ticker)
            .order_by('date')
            .values_list('close', flat=True)
        )
        price_list = [float(p) for p in prices]
        if len(price_list) < 5:
            return None

        price_list = price_list[-days:]

        fig, ax = plt.subplots(figsize=(3, 1), dpi=100)
        cls._apply_dark_style(fig, ax)
        color = cls.GAIN_COLOR if price_list[-1] >= price_list[0] else cls.LOSS_COLOR
        ax.plot(range(len(price_list)), price_list, color=color, linewidth=1.5)
        ax.fill_between(range(len(price_list)), price_list, alpha=0.1, color=color)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.grid(False)
        plt.tight_layout(pad=0.1)
        return cls._fig_to_bytes(fig)

    @classmethod
    def generate_opportunity_score_chart(cls, holdings_with_indicators):
        """Bar chart of opportunity scores for holdings."""
        symbols = []
        scores = []
        for h, ind in holdings_with_indicators:
            if ind and ind.opportunity_score is not None:
                symbols.append(h['ticker'].symbol)
                scores.append(ind.opportunity_score)

        if not scores:
            return None

        fig, ax = plt.subplots(figsize=(5, max(2, len(symbols) * 0.4)), dpi=100)
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
        ax.set_title('Opportunity Scores', fontsize=10, fontweight='bold')
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
    def gather_report_data():
        portfolios = Portfolio.objects.prefetch_related('lots__ticker').all()
        report_portfolios = []

        for portfolio in portfolios:
            holdings = portfolio.get_holdings()
            holdings_data = []
            for h in holdings:
                ticker = h['ticker']
                try:
                    indicators = ticker.indicators
                except IndicatorSnapshot.DoesNotExist:
                    indicators = None

                try:
                    ai_analysis = ticker.ai_analysis
                except AIAnalysis.DoesNotExist:
                    ai_analysis = None

                news = list(NewsArticle.objects.filter(
                    ticker=ticker,
                ).order_by('-published_at')[:3])

                holdings_data.append({
                    'holding': h,
                    'indicators': indicators,
                    'ai_analysis': ai_analysis,
                    'news': news,
                })

            report_portfolios.append({
                'portfolio': portfolio,
                'holdings': holdings,
                'holdings_data': holdings_data,
            })

        return {
            'portfolios': report_portfolios,
            'generated_at': timezone.localtime(timezone.now()),
        }

    @staticmethod
    def refresh_portfolio_data():
        """Refresh quotes, indicators, news, and AI analysis for all portfolio tickers."""
        import time
        from market.services import StockDataService
        from analysis.services import AIAnalysisService

        tickers = set()
        for portfolio in Portfolio.objects.prefetch_related('lots__ticker').all():
            for lot in portfolio.lots.all():
                tickers.add(lot.ticker)

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
    def generate_and_send():
        EmailReportService.refresh_portfolio_data()
        data = EmailReportService.gather_report_data()

        recipient = settings.REPORT_RECIPIENT_EMAIL
        if not recipient:
            raise ValueError(
                'REPORT_RECIPIENT_EMAIL is not configured. '
                'Set it in your environment variables.'
            )

        portfolio_count = len(data['portfolios'])
        ticker_count = sum(
            len(pdata['holdings_data']) for pdata in data['portfolios']
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

                gl_bytes = ReportChartService.generate_gain_loss_bar_chart(holdings)
                if gl_bytes:
                    cid = f'{prefix}_gainloss'
                    images[cid] = gl_bytes
                    pdata['gainloss_chart_cid'] = cid

                holdings_with_indicators = [
                    (hd['holding'], hd['indicators'])
                    for hd in pdata['holdings_data']
                ]
                opp_bytes = ReportChartService.generate_opportunity_score_chart(
                    holdings_with_indicators
                )
                if opp_bytes:
                    cid = f'{prefix}_opportunity'
                    images[cid] = opp_bytes
                    pdata['opportunity_chart_cid'] = cid

                for hd in pdata['holdings_data']:
                    ticker = hd['holding']['ticker']
                    spark_bytes = ReportChartService.generate_price_sparkline(ticker)
                    if spark_bytes:
                        cid = f'spark_{ticker.symbol.lower()}'
                        images[cid] = spark_bytes
                        hd['sparkline_cid'] = cid

            html_content = render_to_string('portfolio/email_report.html', data)

            subject = f'Portfolio Report - {data["generated_at"].strftime("%B %d, %Y")}'
            text_content = 'Your portfolio report. Please view in an HTML-capable email client.'
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
