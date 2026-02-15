"""Transaction forms with Material 3 styled widgets."""
from django import forms
from django.db.models import Q
from .models import Transaction, Category, Budget, SavingsGoal

tw = "w-full px-4 py-3 rounded-xl border border-m3-outline-variant dark:border-m3-outline-variant-dark bg-m3-surface-container-high dark:bg-m3-surface-container-high-dark text-m3-on-surface dark:text-m3-on-surface-dark focus:ring-2 focus:ring-m3-primary dark:focus:ring-m3-primary-dark focus:border-transparent outline-none transition-all duration-200"
tw_select = tw
tw_date = tw + " date-input"
tw_textarea = tw + " resize-none"


class CategorySelect(forms.Select):
    template_name = "transactions/widgets/category_select.html"

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        # Verify if categories are attached to the widget instance
        if hasattr(self, 'categories'):
            context['categories'] = self.categories
        else:
            context['categories'] = Category.objects.all()
        return context

class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ["amount", "type", "category", "date", "payment_method", "notes"]
        widgets = {
            "amount": forms.NumberInput(attrs={"class": tw, "placeholder": "0.00", "step": "0.01", "min": "0.01"}),
            "type": forms.Select(attrs={"class": tw_select}),
            "category": CategorySelect(attrs={"class": tw}),
            "date": forms.DateTimeInput(attrs={"class": tw_date, "type": "datetime-local"}),
            "payment_method": forms.Select(attrs={"class": tw_select}),
            "notes": forms.Textarea(attrs={"class": tw_textarea, "placeholder": "Add a note...", "rows": 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            qs = Category.objects.filter(Q(is_system=True) | Q(user=user))
            self.fields["category"].queryset = qs
            self.fields["category"].widget.categories = qs


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "icon", "color"]
        widgets = {
            "name": forms.TextInput(attrs={"class": tw, "placeholder": "Category name"}),
            "icon": forms.TextInput(attrs={"class": tw, "placeholder": "e.g. restaurant, home, shopping_bag"}),
            "color": forms.TextInput(attrs={"class": tw, "type": "color", "style": "height: 48px; padding: 4px;"}),
        }


class BudgetForm(forms.ModelForm):
    class Meta:
        model = Budget
        fields = ["category", "amount", "month"]
        widgets = {
            "category": CategorySelect(attrs={"class": tw}),
            "amount": forms.NumberInput(attrs={"class": tw, "placeholder": "Budget amount", "step": "0.01", "min": "0.01"}),
            "month": forms.DateInput(attrs={"class": tw_date, "type": "date"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            qs = Category.objects.filter(Q(is_system=True) | Q(user=user))
            self.fields["category"].queryset = qs
            self.fields["category"].widget.categories = qs


class SavingsGoalForm(forms.ModelForm):
    class Meta:
        model = SavingsGoal
        fields = ["name", "target_amount", "current_amount", "icon", "color", "deadline"]
        widgets = {
            "name": forms.TextInput(attrs={"class": tw, "placeholder": "e.g. Emergency Fund"}),
            "target_amount": forms.NumberInput(attrs={"class": tw, "placeholder": "Target amount", "step": "0.01", "min": "0.01"}),
            "current_amount": forms.NumberInput(attrs={"class": tw, "placeholder": "Already saved", "step": "0.01", "min": "0"}),
            "icon": forms.Select(attrs={"class": tw_select}),
            "color": forms.TextInput(attrs={"class": tw, "type": "color", "style": "height: 48px; padding: 4px;"}),
            "deadline": forms.DateInput(attrs={"class": tw_date, "type": "date"}),
        }
