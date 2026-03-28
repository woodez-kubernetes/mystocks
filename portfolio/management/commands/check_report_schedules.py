import logging
import signal
import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from portfolio.models import ReportSchedule

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Long-running scheduler that checks for due report schedules every 60 seconds.'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.running = True

    def add_arguments(self, parser):
        parser.add_argument(
            '--once', action='store_true',
            help='Run a single check and exit (useful for testing).',
        )
        parser.add_argument(
            '--interval', type=int, default=60,
            help='Seconds between checks (default: 60).',
        )

    def handle(self, *args, **options):
        run_once = options['once']
        interval = options['interval']

        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)

        self.stdout.write(self.style.SUCCESS(
            f"Report scheduler started (interval: {interval}s)"
        ))

        while self.running:
            self._check_schedules()
            if run_once:
                break
            time.sleep(interval)

        self.stdout.write("Scheduler stopped.")

    def _shutdown(self, signum, frame):
        self.stdout.write("Shutdown signal received, stopping...")
        self.running = False

    def _check_schedules(self):
        from portfolio.report_service import EmailReportService

        now = timezone.localtime(timezone.now())
        schedules = ReportSchedule.objects.filter(enabled=True).select_related('user')

        for schedule in schedules:
            if schedule.is_due(now):
                self.stdout.write(
                    f"Schedule {schedule} for user {schedule.user.username} is due, sending report..."
                )
                try:
                    EmailReportService.generate_and_send(user=schedule.user)
                    schedule.last_run = now
                    schedule.save(update_fields=['last_run'])
                    self.stdout.write(self.style.SUCCESS(
                        f"Report sent for schedule: {schedule}"
                    ))
                except Exception as e:
                    logger.exception(f"Failed to send scheduled report: {schedule}")
                    self.stdout.write(self.style.ERROR(
                        f"Failed to send report for schedule {schedule}: {e}"
                    ))
