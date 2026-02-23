from django import forms

from .models import Lot, Portfolio, ReportSchedule, Ticker


class PortfolioForm(forms.ModelForm):
    class Meta:
        model = Portfolio
        fields = ['name', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Tech Growth',
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Optional notes about this portfolio...',
            }),
        }


class ReportScheduleForm(forms.ModelForm):
    class Meta:
        model = ReportSchedule
        fields = ['time', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday']
        widgets = {
            'time': forms.TimeInput(attrs={
                'class': 'form-control',
                'type': 'time',
            }),
            'monday': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'tuesday': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'wednesday': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'thursday': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'friday': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'monday': 'Mon',
            'tuesday': 'Tue',
            'wednesday': 'Wed',
            'thursday': 'Thu',
            'friday': 'Fri',
        }


class LotForm(forms.ModelForm):
    symbol = forms.CharField(
        max_length=10,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. AAPL',
            'autocomplete': 'off',
            'list': 'ticker-suggestions',
        }),
        help_text='Enter a stock ticker symbol',
    )

    class Meta:
        model = Lot
        fields = ['shares', 'cost_basis', 'purchase_date', 'notes']
        widgets = {
            'shares': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. 100',
                'step': '0.0001',
                'min': '0.0001',
            }),
            'cost_basis': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. 150.00',
                'step': '0.01',
                'min': '0.01',
            }),
            'purchase_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Optional notes...',
            }),
        }
        labels = {
            'cost_basis': 'Price per share ($)',
        }

    def __init__(self, *args, **kwargs):
        self.portfolio = kwargs.pop('portfolio', None)
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['symbol'].initial = self.instance.ticker.symbol

    def clean_symbol(self):
        symbol = self.cleaned_data['symbol'].upper().strip()
        if not symbol:
            raise forms.ValidationError('Ticker symbol is required.')
        return symbol

    def save(self, commit=True):
        lot = super().save(commit=False)
        symbol = self.cleaned_data['symbol']
        ticker, _ = Ticker.objects.get_or_create(
            symbol=symbol,
            defaults={'company_name': ''},
        )
        lot.ticker = ticker
        if self.portfolio:
            lot.portfolio = self.portfolio
        if commit:
            lot.save()
        return lot
