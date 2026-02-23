from django.contrib import admin

from .models import Lot, Portfolio, Ticker, WatchlistItem


@admin.register(Ticker)
class TickerAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'company_name', 'sector', 'last_price', 'last_updated')
    search_fields = ('symbol', 'company_name')
    list_filter = ('sector',)


class LotInline(admin.TabularInline):
    model = Lot
    extra = 1
    fields = ('ticker', 'shares', 'cost_basis', 'purchase_date', 'notes')


@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')
    inlines = [LotInline]


@admin.register(Lot)
class LotAdmin(admin.ModelAdmin):
    list_display = ('portfolio', 'ticker', 'shares', 'cost_basis', 'purchase_date')
    list_filter = ('portfolio', 'ticker')


@admin.register(WatchlistItem)
class WatchlistItemAdmin(admin.ModelAdmin):
    list_display = ('ticker', 'added_at', 'notes')
    readonly_fields = ('added_at',)
