import random
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from split_expense.models import Friendship, Group, GroupMember, Expense, ExpenseSplit, Settlement

class Command(BaseCommand):
    """
    Usage Example:
    # Generate data for user 'abdulla'
    python manage.py seed_split_data --username abdulla

    # Delete data for user 'abdulla'
    python manage.py seed_split_data --username abdulla --delete
    """
    help = 'Seeds fake friends and splitwise data for testing in production.'

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, required=True, help='The username to generate data for (e.g. abdulla)')
        parser.add_argument('--delete', action='store_true', help='Delete the fake data instead of creating it')

    def handle(self, *args, **kwargs):
        username = kwargs['username']
        delete_mode = kwargs['delete']

        try:
            main_user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User "{username}" does not exist.'))
            return

        fake_usernames = [
            f'{username}_fake_alice',
            f'{username}_fake_bob',
            f'{username}_fake_charlie',
            f'{username}_fake_diana'
        ]

        if delete_mode:
            self.stdout.write(f'Deleting fake data for {username}...')
            # Delete fake users (which cascades and deletes friendships, groups, expenses, etc.)
            deleted, _ = User.objects.filter(username__in=fake_usernames).delete()
            self.stdout.write(self.style.SUCCESS(f'Successfully deleted {deleted} fake users and their associated data.'))
            
            # Delete groups created by the main user that have the word "Fake" in them just in case
            Group.objects.filter(created_by=main_user, name__startswith='(Fake)').delete()
            return

        self.stdout.write(f'Generating realistic fake data for {username}...')

        # 1. Create Fake Friends
        fake_users = []
        names = ['Alice Smith', 'Bob Jones', 'Charlie Brown', 'Diana Prince']
        for i, uname in enumerate(fake_usernames):
            first_name = names[i].split()[0]
            last_name = names[i].split()[1]
            user, created = User.objects.get_or_create(
                username=uname,
                defaults={
                    'email': f'{uname}@example.com',
                    'first_name': first_name,
                    'last_name': last_name
                }
            )
            if created:
                user.set_password('fakepassword123')
                user.save()
            fake_users.append(user)
            
            # Create friendships
            Friendship.objects.get_or_create(user=main_user, friend=user)
            Friendship.objects.get_or_create(user=user, friend=main_user)

        self.stdout.write('Created fake friends.')

        # 2. Create a Fake Group
        group, _ = Group.objects.get_or_create(
            name='(Fake) Goa Trip 🏖️',
            created_by=main_user,
            defaults={'color': '#FF5722', 'icon': 'flight'}
        )

        # Add members
        GroupMember.objects.get_or_create(group=group, user=main_user, defaults={'is_accepted': True})
        for f_user in fake_users:
            GroupMember.objects.get_or_create(group=group, user=f_user, defaults={'is_accepted': True})

        self.stdout.write('Created fake group "Goa Trip".')

        # 3. Add Fake Expenses
        from split_expense.services import create_expense, create_settlement
        
        expenses_data = [
            {'desc': 'Flight Tickets', 'amount': 12000.00, 'paid_by': main_user},
            {'desc': 'Hotel Booking', 'amount': 8500.00, 'paid_by': fake_users[0]},
            {'desc': 'Dinner at Shacks', 'amount': 3200.00, 'paid_by': fake_users[1]},
            {'desc': 'Scuba Diving', 'amount': 6000.00, 'paid_by': main_user},
            {'desc': 'Cab to Airport', 'amount': 1500.00, 'paid_by': fake_users[2]},
        ]

        # Ensure expenses are clean before we seed again to prevent infinite piling
        Expense.objects.filter(group=group).delete()
        
        # Reset balances for all members before adding expenses
        GroupMember.objects.filter(group=group).update(total_paid=0, total_owed=0, net_balance=0)
        
        for ed in expenses_data:
            create_expense(
                group=group,
                paid_by=ed['paid_by'],
                created_by=main_user,
                amount=Decimal(str(ed['amount'])),
                description=ed['desc'],
                split_type='equal'
            )

        self.stdout.write('Added 5 realistic expenses.')

        # 4. Add a Fake Settlement
        Settlement.objects.filter(group=group).delete()
        create_settlement(
            group=group,
            paid_by=fake_users[3], # Diana
            paid_to=main_user,
            amount=Decimal('2000.00')
        )
        self.stdout.write('Added 1 settlement.')

        self.stdout.write(self.style.SUCCESS('Successfully seeded fake splitwise data!'))
