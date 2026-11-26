from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from api.authentication import APIToken
from transactions.models import Budget, Category, Transaction
from transactions.services import ensure_current_month_budgets


class BudgetRepeatAndOverallTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("u", "u@example.com", "pw")
        self.token = APIToken.generate_token(self.user)
        key = getattr(self.token, "key", self.token)
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {key}"}
        self.food = Category.objects.create(name="Food", icon="restaurant", is_system=True)
        self.fun = Category.objects.create(name="Fun", icon="movie", is_system=True)

    def test_only_repeating_budgets_are_copied_with_leftover_when_asked(self):
        oct1 = date(2026, 10, 1)
        Budget.objects.create(user=self.user, category=self.food, amount=Decimal("6000"), month=oct1, carry_over=True)
        Budget.objects.create(user=self.user, category=self.fun, amount=Decimal("2000"), month=oct1, repeat=False)
        Transaction.objects.create(user=self.user, amount=Decimal("5500"), type="expense", category=self.food,
                                   date=timezone.make_aware(datetime(2026, 10, 10, 12)))
        ensure_current_month_budgets(self.user, date(2026, 11, 5))
        nov = Budget.objects.filter(user=self.user, month=date(2026, 11, 1))
        self.assertEqual(nov.count(), 1)
        food = nov.get()
        self.assertEqual(food.carried, Decimal("500"))
        self.assertEqual(food.amount, Decimal("6500"))
        # next month: base stays 6000, only the new leftover is carried
        ensure_current_month_budgets(self.user, date(2026, 12, 2))
        dec = Budget.objects.get(user=self.user, month=date(2026, 12, 1))
        self.assertEqual(dec.amount, Decimal("6000") + Decimal("6500"))
        self.assertEqual(dec.carried, Decimal("6500"))

    def test_overall_budget_set_and_listed(self):
        r = self.client.put("/api/budgets/overall/", data='{"amount": "20000"}', content_type="application/json", **self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["overall"]["amount"], "20000.00")
        r = self.client.get("/api/budgets/", **self.auth)
        self.assertEqual(r.json()["overall"]["amount"], "20000.00")

    def test_post_saves_repeat_and_carry(self):
        r = self.client.post("/api/budgets/", data='{"category_id": %d, "amount": "3000", "repeat": false, "carry_over": true}' % self.food.id,
                             content_type="application/json", **self.auth)
        self.assertIn(r.status_code, (200, 201))
        b = r.json()["budget"]
        self.assertFalse(b["repeat"])
        self.assertTrue(b["carry_over"])
        self.assertEqual(Decimal(b["carried"]), 0)
