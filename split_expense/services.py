from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from .models import Group, GroupMember, Expense, ExpenseSplit, Settlement, GroupInvitation

@transaction.atomic
def create_expense(group, paid_by, amount, description, split_type, splits_data=None):
    """
    Creates an expense, calculates splits, and updates group member balances.
    
    splits_data format (optional, needed for exact/percentage):
    [
        {'user': user_instance, 'value': Decimal('100.00')}  # value is amount or percentage
    ]
    """
    amount = Decimal(str(amount))
    
    # 1. Create the Expense
    expense = Expense.objects.create(
        group=group,
        paid_by=paid_by,
        amount=amount,
        description=description,
        split_type=split_type
    )
    
    members = list(group.members.all())
    num_members = len(members)
    
    if num_members == 0:
        raise ValidationError("Cannot create an expense in an empty group.")
        
    splits_to_create = []
    
    # 2. Calculate Splits
    if split_type == 'equal':
        # Split amount equally, adjust for rounding errors on the first person
        base_split = round(amount / num_members, 2)
        total_split = base_split * num_members
        difference = amount - total_split
        
        for i, member in enumerate(members):
            owed = base_split
            if i == 0:
                owed += difference  # Give the rounding difference to the first member
            
            splits_to_create.append(
                ExpenseSplit(expense=expense, user=member, amount_owed=owed)
            )
            
    elif split_type == 'exact':
        if not splits_data:
            raise ValidationError("Splits data is required for exact splits.")
            
        total_exact = sum(Decimal(str(item['value'])) for item in splits_data)
        if total_exact != amount:
            raise ValidationError(f"Total exact split ({total_exact}) must match expense amount ({amount}).")
            
        for item in splits_data:
            splits_to_create.append(
                ExpenseSplit(expense=expense, user=item['user'], amount_owed=Decimal(str(item['value'])))
            )
            
    elif split_type == 'percentage':
        if not splits_data:
            raise ValidationError("Splits data is required for percentage splits.")
            
        total_percent = sum(Decimal(str(item['value'])) for item in splits_data)
        if total_percent != Decimal('100'):
            raise ValidationError(f"Total percentage ({total_percent}) must equal 100%.")
            
        calculated_total = Decimal('0')
        for i, item in enumerate(splits_data):
            percent = Decimal(str(item['value']))
            owed = round(amount * (percent / Decimal('100')), 2)
            
            if i == len(splits_data) - 1:
                # Adjust rounding on the last person
                owed = amount - calculated_total
            else:
                calculated_total += owed
                
            splits_to_create.append(
                ExpenseSplit(expense=expense, user=item['user'], amount_owed=owed, percentage=percent)
            )
    else:
        raise ValidationError(f"Invalid split type: {split_type}")
        
    ExpenseSplit.objects.bulk_create(splits_to_create)
    
    # 3. Update the Virtual Ledger (GroupMember balances)
    # Update paid_by (total_paid)
    payer, _ = GroupMember.objects.get_or_create(group=group, user=paid_by)
    payer.total_paid += amount
    payer.net_balance += amount
    payer.save(update_fields=['total_paid', 'net_balance'])
    
    # Update all who owe
    for split in splits_to_create:
        member_ledger, _ = GroupMember.objects.get_or_create(group=group, user=split.user)
        member_ledger.total_owed += split.amount_owed
        member_ledger.net_balance -= split.amount_owed
        member_ledger.save(update_fields=['total_owed', 'net_balance'])

    return expense

def calculate_simplified_debts(group):
    """
    Returns a list of simplified transactions to settle all group debts.
    Format: [{'from': User, 'to': User, 'amount': Decimal}]
    """
    members = GroupMember.objects.filter(group=group).select_related('user')
    
    debtors = []   # People who owe money (net_balance < 0)
    creditors = [] # People who are owed money (net_balance > 0)
    
    for member in members:
        if member.net_balance < -Decimal('0.01'):
            debtors.append({'user': member.user, 'balance': abs(member.net_balance)})
        elif member.net_balance > Decimal('0.01'):
            creditors.append({'user': member.user, 'balance': member.net_balance})
            
    # Sort by largest balances first to optimize
    debtors.sort(key=lambda x: x['balance'], reverse=True)
    creditors.sort(key=lambda x: x['balance'], reverse=True)
    
    transactions = []
    
    i, j = 0, 0
    while i < len(debtors) and j < len(creditors):
        debtor = debtors[i]
        creditor = creditors[j]
        
        # Determine the minimum amount that can be settled between the two
        settle_amount = min(debtor['balance'], creditor['balance'])
        
        # Ensure we don't create 0 amount transactions (due to float precision)
        if settle_amount > Decimal('0.01'):
            transactions.append({
                'from': debtor['user'],
                'to': creditor['user'],
                'amount': round(settle_amount, 2)
            })
        
        # Deduct the settled amount
        debtor['balance'] -= settle_amount
        creditor['balance'] -= settle_amount
        
        if debtor['balance'] < Decimal('0.01'):
            i += 1
        if creditor['balance'] < Decimal('0.01'):
            j += 1
            
    return transactions

@transaction.atomic
def create_settlement(group, paid_by, paid_to, amount):
    """
    Records a settlement payment and updates the virtual ledger.
    """
    amount = Decimal(str(amount))
    
    settlement = Settlement.objects.create(
        group=group,
        paid_by=paid_by,
        paid_to=paid_to,
        amount=amount
    )
    
    # Adjust balances
    # The person paying is reducing their debt (they are "owed" back what they pay)
    payer_ledger, _ = GroupMember.objects.get_or_create(group=group, user=paid_by)
    payer_ledger.total_paid += amount
    payer_ledger.net_balance += amount
    payer_ledger.save(update_fields=['total_paid', 'net_balance'])
    
    # The person receiving is getting money (they "owe" the system what they receive)
    receiver_ledger, _ = GroupMember.objects.get_or_create(group=group, user=paid_to)
    receiver_ledger.total_owed += amount
    receiver_ledger.net_balance -= amount
    receiver_ledger.save(update_fields=['total_owed', 'net_balance'])
    
    return settlement

@transaction.atomic
def delete_expense(expense):
    """
    Reverses the ledger impact of an expense and deletes it.
    """
    group = expense.group
    amount = expense.amount
    
    # 1. Reverse the payer's total_paid and net_balance
    payer_ledger = GroupMember.objects.get(group=group, user=expense.paid_by)
    payer_ledger.total_paid -= amount
    payer_ledger.net_balance -= amount
    payer_ledger.save(update_fields=['total_paid', 'net_balance'])
    
    # 2. Reverse each split's impact on total_owed and net_balance
    for split in expense.splits.select_related('user'):
        member_ledger = GroupMember.objects.get(group=group, user=split.user)
        member_ledger.total_owed -= split.amount_owed
        member_ledger.net_balance += split.amount_owed
        member_ledger.save(update_fields=['total_owed', 'net_balance'])
    
    # 3. Delete the expense (cascades to ExpenseSplit)
    expense.delete()

@transaction.atomic
def update_expense(expense, paid_by, amount, description, split_type, splits_data=None):
    """
    Updates an expense by reversing the old ledger impact and creating a new one.
    Returns the new expense object.
    """
    group = expense.group
    
    # 1. Reverse the old expense's ledger impact
    old_amount = expense.amount
    
    payer_ledger = GroupMember.objects.get(group=group, user=expense.paid_by)
    payer_ledger.total_paid -= old_amount
    payer_ledger.net_balance -= old_amount
    payer_ledger.save(update_fields=['total_paid', 'net_balance'])
    
    for split in expense.splits.select_related('user'):
        member_ledger = GroupMember.objects.get(group=group, user=split.user)
        member_ledger.total_owed -= split.amount_owed
        member_ledger.net_balance += split.amount_owed
        member_ledger.save(update_fields=['total_owed', 'net_balance'])
    
    # 2. Delete the old expense
    expense.delete()
    
    # 3. Create the new expense using the existing service function
    return create_expense(
        group=group,
        paid_by=paid_by,
        amount=amount,
        description=description,
        split_type=split_type,
        splits_data=splits_data
    )

@transaction.atomic
def remove_member(group, user):
    """
    Removes a member from a group. Only allowed if their net balance is zero.
    """
    try:
        member = GroupMember.objects.get(group=group, user=user)
    except GroupMember.DoesNotExist:
        raise ValidationError("User is not a member of this group.")
    
    if member.net_balance != Decimal('0'):
        raise ValidationError(
            f"{user.get_full_name() or user.username} has an unsettled balance of "
            f"{member.net_balance}. Please settle all debts before removing."
        )
    
    # Delete the membership
    member.delete()
    
    # Also remove any pending invitation for this user's email
    if user.email:
        GroupInvitation.objects.filter(group=group, email=user.email).delete()

