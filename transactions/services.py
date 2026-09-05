from datetime import date
from django.utils import timezone
from .models import Budget

def ensure_current_month_budgets(user, date_context=None):
    """
    Ensures that the user has budgets for the current month.
    If none exist, carries forward the most recent past budgets automatically.
    
    This function is safe against duplicate records thanks to Budget's
    unique_together constraint on [user, category, month].
    """
    if date_context is None:
        date_context = timezone.localdate()
        
    current_month_start = date_context.replace(day=1)
    
    # Check if any budgets already exist for this user in the current month
    exists = Budget.objects.filter(
        user=user, 
        month__year=current_month_start.year, 
        month__month=current_month_start.month
    ).exists()
    
    if not exists:
        # No budgets for this month. Find the most recent historical month that has budgets.
        last_budget = Budget.objects.filter(
            user=user, 
            month__lt=current_month_start
        ).order_by("-month").first()
        
        if last_budget:
            last_month = last_budget.month
            past_budgets = Budget.objects.filter(
                user=user, 
                month__year=last_month.year, 
                month__month=last_month.month
            )
            
            # Duplicate the past budgets for the current month
            new_budgets = []
            for pb in past_budgets:
                new_budgets.append(
                    Budget(
                        user=user,
                        category=pb.category,
                        amount=pb.amount,
                        month=current_month_start
                    )
                )
            
            if new_budgets:
                Budget.objects.bulk_create(new_budgets)
