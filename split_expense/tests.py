from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from .models import Group, GroupMember, Expense, Settlement
from .services import create_expense, calculate_simplified_debts, create_settlement

class SplitServicesTest(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(username='alice', password='password')
        self.user2 = User.objects.create_user(username='bob', password='password')
        self.user3 = User.objects.create_user(username='charlie', password='password')
        
        self.group = Group.objects.create(name='Trip', created_by=self.user1)
        GroupMember.objects.create(group=self.group, user=self.user1)
        GroupMember.objects.create(group=self.group, user=self.user2)
        GroupMember.objects.create(group=self.group, user=self.user3)

    def test_equal_split(self):
        # Alice pays 300, equal split among 3 (100 each)
        expense = create_expense(
            group=self.group,
            paid_by=self.user1,
            amount=Decimal('300.00'),
            description='Lunch',
            split_type='equal'
        )
        
        self.assertEqual(expense.splits.count(), 3)
        
        m1 = GroupMember.objects.get(group=self.group, user=self.user1)
        m2 = GroupMember.objects.get(group=self.group, user=self.user2)
        m3 = GroupMember.objects.get(group=self.group, user=self.user3)
        
        # internal balances: 
        # Alice paid 300, owed 100 -> net +200
        # Bob paid 0, owed 100 -> net -100
        # Charlie paid 0, owed 100 -> net -100
        self.assertEqual(m1.net_balance, Decimal('200.00'))
        self.assertEqual(m2.net_balance, Decimal('-100.00'))
        self.assertEqual(m3.net_balance, Decimal('-100.00'))

    def test_exact_split(self):
        splits_data = [
            {'user': self.user1, 'value': Decimal('50.00')},
            {'user': self.user2, 'value': Decimal('150.00')},
            {'user': self.user3, 'value': Decimal('0.00')},
        ]
        
        create_expense(
            group=self.group,
            paid_by=self.user1,
            amount=Decimal('200.00'),
            description='Dinner',
            split_type='exact',
            splits_data=splits_data
        )
        
        m1 = GroupMember.objects.get(group=self.group, user=self.user1)
        m2 = GroupMember.objects.get(group=self.group, user=self.user2)
        m3 = GroupMember.objects.get(group=self.group, user=self.user3)
        
        # M1: paid 200, owed 50 -> +150
        # M2: paid 0, owed 150 -> -150
        # M3: paid 0, owed 0 -> 0
        self.assertEqual(m1.net_balance, Decimal('150.00'))
        self.assertEqual(m2.net_balance, Decimal('-150.00'))
        self.assertEqual(m3.net_balance, Decimal('0.00'))

    def test_percentage_split_and_simplification(self):
        splits_data = [
            {'user': self.user1, 'value': Decimal('20.00')},
            {'user': self.user2, 'value': Decimal('30.00')},
            {'user': self.user3, 'value': Decimal('50.00')},
        ]
        
        create_expense(
            group=self.group,
            paid_by=self.user2, # Bob pays 1000
            amount=Decimal('1000.00'),
            description='Flight',
            split_type='percentage',
            splits_data=splits_data
        )
        
        m1 = GroupMember.objects.get(group=self.group, user=self.user1)
        m2 = GroupMember.objects.get(group=self.group, user=self.user2)
        m3 = GroupMember.objects.get(group=self.group, user=self.user3)
        
        # Alice (20%): owes 200 -> net -200
        # Bob (30%): paid 1000, owes 300 -> net +700
        # Charlie (50%): owes 500 -> net -500
        self.assertEqual(m1.net_balance, Decimal('-200.00'))
        self.assertEqual(m2.net_balance, Decimal('700.00'))
        self.assertEqual(m3.net_balance, Decimal('-500.00'))
        
        # Test Debt Simplification
        transactions = calculate_simplified_debts(self.group)
        self.assertEqual(len(transactions), 2)
        
        # Charlie (-500) pays Bob (+700) -> 500
        # Alice (-200) pays Bob (+200) -> 200
        
        total_tx_amount = sum(t['amount'] for t in transactions)
        self.assertEqual(total_tx_amount, Decimal('700.00'))
        
        # Settle up one of them
        create_settlement(
            group=self.group,
            paid_by=self.user3,
            paid_to=self.user2,
            amount=Decimal('500.00')
        )
        
        # Post settlement:
        m2.refresh_from_db()
        m3.refresh_from_db()
        
        # M3 paid M2 500. 
        # M3 net balance: -500 -> +500 = 0
        # M2 net balance: +700 -> -500 = +200
        self.assertEqual(m3.net_balance, Decimal('0.00'))
        self.assertEqual(m2.net_balance, Decimal('200.00'))

    def test_delete_expense(self):
        """Create an expense, delete it, verify all balances return to 0."""
        from .services import delete_expense
        
        expense = create_expense(
            group=self.group,
            paid_by=self.user1,
            amount=Decimal('300.00'),
            description='Deletable',
            split_type='equal'
        )
        
        delete_expense(expense)
        
        m1 = GroupMember.objects.get(group=self.group, user=self.user1)
        m2 = GroupMember.objects.get(group=self.group, user=self.user2)
        m3 = GroupMember.objects.get(group=self.group, user=self.user3)
        
        self.assertEqual(m1.net_balance, Decimal('0.00'))
        self.assertEqual(m2.net_balance, Decimal('0.00'))
        self.assertEqual(m3.net_balance, Decimal('0.00'))
        self.assertEqual(Expense.objects.count(), 0)
    
    def test_update_expense(self):
        """Create an expense, update it with a new amount, verify recalculated balances."""
        from .services import update_expense
        
        expense = create_expense(
            group=self.group,
            paid_by=self.user1,
            amount=Decimal('300.00'),
            description='Original',
            split_type='equal'
        )
        
        # Update: user2 now pays 600 equally
        new_expense = update_expense(
            expense=expense,
            paid_by=self.user2,
            amount=Decimal('600.00'),
            description='Updated',
            split_type='equal'
        )
        
        m1 = GroupMember.objects.get(group=self.group, user=self.user1)
        m2 = GroupMember.objects.get(group=self.group, user=self.user2)
        m3 = GroupMember.objects.get(group=self.group, user=self.user3)
        
        # user2 paid 600, each owes 200
        # m1: paid 0, owed 200 -> -200
        # m2: paid 600, owed 200 -> +400
        # m3: paid 0, owed 200 -> -200
        self.assertEqual(m1.net_balance, Decimal('-200.00'))
        self.assertEqual(m2.net_balance, Decimal('400.00'))
        self.assertEqual(m3.net_balance, Decimal('-200.00'))
        self.assertEqual(new_expense.description, 'Updated')
        self.assertEqual(Expense.objects.count(), 1)
    
    def test_remove_member_settled(self):
        """Remove a member with zero balance – should succeed."""
        from .services import remove_member
        
        # user3 has 0 balance (no expenses created)
        remove_member(self.group, self.user3)
        
        self.assertFalse(
            GroupMember.objects.filter(group=self.group, user=self.user3).exists()
        )
    
    def test_remove_member_unsettled(self):
        """Removing a member with non-zero balance should raise ValidationError."""
        from .services import remove_member
        from django.core.exceptions import ValidationError
        
        create_expense(
            group=self.group,
            paid_by=self.user1,
            amount=Decimal('300.00'),
            description='Lunch',
            split_type='equal'
        )
        
        with self.assertRaises(ValidationError):
            remove_member(self.group, self.user2)

