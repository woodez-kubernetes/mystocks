from django.contrib import admin

from analysis.models import AIAnalysis, CIKMapping, IndicatorSnapshot, SECFiling, WhaleActivity


@admin.register(IndicatorSnapshot)
class IndicatorSnapshotAdmin(admin.ModelAdmin):
    list_display = ('ticker', 'opportunity_score', 'rsi', 'rsi_signal', 'macd_signal', 'bb_signal', 'sma_signal', 'sentiment_signal', 'computed_at')
    list_filter = ('rsi_signal', 'macd_signal', 'bb_signal', 'sma_signal', 'sentiment_signal')
    readonly_fields = ('computed_at',)


@admin.register(AIAnalysis)
class AIAnalysisAdmin(admin.ModelAdmin):
    list_display = ('ticker', 'model_name', 'generated_at')
    readonly_fields = ('analysis_text', 'prompt_hash', 'generated_at')


@admin.register(CIKMapping)
class CIKMappingAdmin(admin.ModelAdmin):
    list_display = ('ticker', 'cik', 'updated_at')
    readonly_fields = ('updated_at',)


@admin.register(SECFiling)
class SECFilingAdmin(admin.ModelAdmin):
    list_display = ('ticker', 'form_type', 'filer_name', 'transaction_type', 'shares', 'total_value', 'filed_at')
    list_filter = ('form_type', 'transaction_type')
    readonly_fields = ('created_at',)


@admin.register(WhaleActivity)
class WhaleActivityAdmin(admin.ModelAdmin):
    list_display = ('ticker', 'date', 'signal', 'confidence', 'insider_buy_count', 'insider_sell_count', 'block_trade_detected')
    list_filter = ('signal',)
    readonly_fields = ('computed_at',)
