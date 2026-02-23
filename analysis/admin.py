from django.contrib import admin

from analysis.models import AIAnalysis, IndicatorSnapshot


@admin.register(IndicatorSnapshot)
class IndicatorSnapshotAdmin(admin.ModelAdmin):
    list_display = ('ticker', 'opportunity_score', 'rsi', 'rsi_signal', 'macd_signal', 'bb_signal', 'sma_signal', 'sentiment_signal', 'computed_at')
    list_filter = ('rsi_signal', 'macd_signal', 'bb_signal', 'sma_signal', 'sentiment_signal')
    readonly_fields = ('computed_at',)


@admin.register(AIAnalysis)
class AIAnalysisAdmin(admin.ModelAdmin):
    list_display = ('ticker', 'model_name', 'generated_at')
    readonly_fields = ('analysis_text', 'prompt_hash', 'generated_at')
