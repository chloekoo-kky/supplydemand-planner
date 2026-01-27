from django import forms
from .models import MarketDemand

class ImportDemandForm(forms.Form):
    country = forms.CharField(max_length=50, required=True, widget=forms.TextInput(attrs={'placeholder': 'e.g. Malaysia'}))
    demand_type = forms.ChoiceField(choices=MarketDemand.TYPE_CHOICES, initial='FORECAST')
    file = forms.FileField(help_text="支持 Excel (.xlsx) 或 CSV。列名应包含 SKU 和日期 (如 '2026-01')")

class RunMRPForm(forms.Form):
    target_month = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'month'}),
        help_text="选择你要规划生产的月份"
    )
