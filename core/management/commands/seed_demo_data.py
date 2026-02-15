"""Seed fake transactions and budgets for demo purposes."""
import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db.models import Q

from transactions.models import Transaction, Category, Budget


class Command(BaseCommand):
    help = "Seed realistic demo data (transactions, budgets)"

    def handle(self, *args, **kwargs):
        user = User.objects.first()
        if not user:
            self.stdout.write(self.style.ERROR("No user found. Create a user first."))
            return

        categories = list(Category.objects.filter(Q(is_system=True) | Q(user=user)))
        if not categories:
            self.stdout.write(self.style.ERROR("No categories found. Run seed_categories first."))
            return

        # Map category names to types
        income_names = {"Salary", "Freelance", "Investment", "Gift"}
        income_cats = [c for c in categories if c.name in income_names]
        expense_cats = [c for c in categories if c.name not in income_names]

        today = date.today()
        payment_methods = ["cash", "card", "bank_transfer", "upi"]

        notes_map = {
            "Food & Dining": ["Lunch at cafe", "Grocery shopping", "Dinner takeout", "Morning coffee", "Snacks"],
            "Transport": ["Uber ride", "Gas refill", "Bus ticket", "Parking fee", "Metro card"],
            "Housing": ["Rent payment", "Electricity bill", "Water bill", "Internet bill", "Home repair"],
            "Entertainment": ["Netflix subscription", "Movie tickets", "Concert tickets", "Gaming", "Books"],
            "Shopping": ["New shoes", "Phone case", "Headphones", "Clothes", "Amazon order"],
            "Healthcare": ["Doctor visit", "Pharmacy", "Lab tests", "Gym membership", "Vitamins"],
            "Education": ["Online course", "Books", "Workshop fee", "Certification", "Stationery"],
            "Salary": ["Monthly salary", "Bonus", "Overtime pay"],
            "Freelance": ["Client project", "Consulting fee", "Design work", "Development gig"],
            "Investment": ["Dividend income", "Stock sale", "Interest earned"],
            "Gift": ["Birthday gift received", "Cash gift"],
            "Bills": ["Phone bill", "Insurance", "Subscription", "Cloud storage"],
            "Travel": ["Hotel booking", "Flight ticket", "Travel insurance", "Souvenirs"],
            "Clothing": ["Winter jacket", "Formal shirt", "Running shoes", "Accessories"],
            "Fitness": ["Gym fee", "Protein powder", "Yoga class", "Sports gear"],
            "Pets": ["Pet food", "Vet visit", "Pet toys", "Grooming"],
            "Coffee": ["Starbucks", "Local cafe", "Cold brew", "Espresso beans"],
        }

        created = 0

        # Generate 6 months of data
        for month_offset in range(6):
            month_date = today.replace(day=1) - timedelta(days=30 * month_offset)
            month_start = month_date.replace(day=1)
            if month_offset == 0:
                month_end = today
            else:
                next_month = (month_start.month % 12) + 1
                year = month_start.year + (1 if next_month == 1 else 0)
                month_end = date(year, next_month, 1) - timedelta(days=1)

            days_in_month = (month_end - month_start).days + 1

            # 1-2 income transactions per month
            for _ in range(random.randint(1, 2)):
                cat = random.choice(income_cats) if income_cats else random.choice(categories)
                day = random.randint(1, min(28, days_in_month))
                txn_date = month_start.replace(day=day)
                if txn_date > today:
                    txn_date = today
                notes_list = notes_map.get(cat.name, ["Income"])
                Transaction.objects.create(
                    user=user,
                    amount=Decimal(str(random.choice([2500, 3000, 3500, 4000, 4500, 5000, 5500, 6000]))),
                    type="income",
                    category=cat,
                    date=txn_date,
                    payment_method="bank_transfer",
                    notes=random.choice(notes_list),
                )
                created += 1

            # 8-15 expense transactions per month
            for _ in range(random.randint(8, 15)):
                cat = random.choice(expense_cats) if expense_cats else random.choice(categories)
                day = random.randint(1, min(28, days_in_month))
                txn_date = month_start.replace(day=day)
                if txn_date > today:
                    txn_date = today
                notes_list = notes_map.get(cat.name, ["Expense"])
                amount_ranges = {
                    "Housing": (800, 2000),
                    "Food & Dining": (5, 80),
                    "Transport": (5, 50),
                    "Entertainment": (10, 60),
                    "Shopping": (20, 200),
                    "Healthcare": (20, 150),
                    "Education": (30, 200),
                    "Bills": (15, 100),
                    "Travel": (50, 500),
                    "Clothing": (25, 150),
                    "Fitness": (20, 80),
                    "Coffee": (3, 12),
                }
                low, high = amount_ranges.get(cat.name, (10, 100))
                Transaction.objects.create(
                    user=user,
                    amount=Decimal(str(round(random.uniform(low, high), 2))),
                    type="expense",
                    category=cat,
                    date=txn_date,
                    payment_method=random.choice(payment_methods),
                    notes=random.choice(notes_list),
                )
                created += 1

        # Create budgets for current month
        budget_cats = random.sample(expense_cats, min(4, len(expense_cats)))
        budgets_created = 0
        for cat in budget_cats:
            Budget.objects.get_or_create(
                user=user,
                category=cat,
                month=today.replace(day=1),
                defaults={"amount": Decimal(str(random.choice([200, 300, 400, 500, 750, 1000])))},
            )
            budgets_created += 1

        self.stdout.write(self.style.SUCCESS(
            f"✅ Seeded {created} transactions, {budgets_created} budgets."
        ))
