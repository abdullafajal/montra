from django.contrib import admin
from .models import Group, GroupMember, Expense, ExpenseSplit, Settlement, GroupInvitation

@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name", "created_by", "created_at")
    search_fields = ("name",)
    list_filter = ("created_at",)
    readonly_fields = ("created_at",)

@admin.register(GroupMember)
class GroupMemberAdmin(admin.ModelAdmin):
    list_display = ("group", "user", "net_balance", 'reminders_sent_today', 'last_reminded_at')
    search_fields = ("group__name", "user__username")
    list_filter = ("net_balance",)
    readonly_fields = ("joined_at",)

@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("description", "amount", "paid_by", "date")
    search_fields = ("description",)
    list_filter = ("date",)
    readonly_fields = ("created_at",)

@admin.register(ExpenseSplit)
class ExpenseSplitAdmin(admin.ModelAdmin):
    list_display = ("expense", "user", "amount_owed")
    search_fields = ("expense__description", "user__username")
    list_filter = ("expense__date",)

@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = ("group", "paid_by", "paid_to", "amount", "date")
    search_fields = ("group__name", "paid_by__username", "paid_to__username")
    list_filter = ("date",)
    readonly_fields = ("created_at",)

@admin.register(GroupInvitation)
class GroupInvitationAdmin(admin.ModelAdmin):
    list_display = ("group", "email", "invited_by", "created_at")
    search_fields = ("group__name", "email", "invited_by__username")
    list_filter = ("created_at",)
    readonly_fields = ("token", "created_at")

# admin.site.register(Group, GroupAdmin)
# admin.site.register(GroupMember, GroupMemberAdmin)
# admin.site.register(Expense, ExpenseAdmin)
# admin.site.register(ExpenseSplit, ExpenseSplitAdmin)
# admin.site.register(Settlement, SettlementAdmin)
# admin.site.register(GroupInvitation, GroupInvitationAdmin)