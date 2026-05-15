from django.urls import path
from . import views

app_name = 'split_expense'

urlpatterns = [
    path('', views.GroupListView.as_view(), name='group_list'),
    
    # Friend System
    path('friends/', views.FriendListView.as_view(), name='friend_list'),
    path('friends/add/', views.SendFriendRequestView.as_view(), name='friend_request_send'),
    path('friends/request/<int:request_id>/<str:action>/', views.FriendRequestActionView.as_view(), name='friend_request_action'),
    
    path('setup/', views.GroupCreateView.as_view(), name='group_create'),
    path('<int:pk>/', views.GroupDetailView.as_view(), name='group_detail'),
    path('<int:pk>/edit/', views.GroupUpdateView.as_view(), name='group_edit'),
    path('<int:pk>/delete/', views.GroupDeleteView.as_view(), name='group_delete'),
    path('<int:group_id>/expense/add/', views.ExpenseCreateView.as_view(), name='expense_create'),
    path('<int:group_id>/expense/<int:expense_id>/', views.ExpenseDetailView.as_view(), name='expense_detail'),
    path('<int:group_id>/expense/<int:expense_id>/edit/', views.ExpenseUpdateView.as_view(), name='expense_edit'),
    path('<int:group_id>/expense/<int:expense_id>/delete/', views.ExpenseDeleteView.as_view(), name='expense_delete'),
    path('<int:group_id>/settle/confirm/', views.SettlementConfirmView.as_view(), name='settlement_confirm'),
    path('<int:group_id>/remind/confirm/', views.ReminderConfirmView.as_view(), name='reminder_confirm'),
    path('<int:group_id>/settle/', views.SettlementCreateView.as_view(), name='settlement_create'),
    path('<int:group_id>/remind/', views.SendReminderView.as_view(), name='send_reminder'),
    path('<int:group_id>/members/add/', views.GroupMemberAddView.as_view(), name='group_member_add'),
    path('<int:group_id>/members/<int:user_id>/remove/', views.GroupMemberRemoveView.as_view(), name='group_member_remove'),
    path('<int:group_id>/leave/', views.GroupLeaveView.as_view(), name='group_leave'),
    
    path('invitations/', views.InvitationListView.as_view(), name='invitations'),
    path('invite/<uuid:token>/', views.InvitationAcceptSpecialView.as_view(), name='invitation_special_link'),
    path('<int:group_id>/invite/<str:action>/', views.InvitationActionView.as_view(), name='invitation_action'),
    path('api/users/search/', views.UserSearchAPIView.as_view(), name='api_user_search'),
]
