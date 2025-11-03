from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views, auth_views

urlpatterns = [
    path('auth/register', auth_views.register, name='register'),
    path('auth/login', auth_views.login, name='login'),
    path('auth/refresh', TokenRefreshView.as_view(), name='token-refresh'),
    path('auth/me', auth_views.me, name='me'),
    path('auth/profile', auth_views.update_profile, name='update-profile'),
    path('auth/change-password', auth_views.change_password, name='change-password'),

    path('users', auth_views.UserListCreateView.as_view(), name='users-list-create'),
    path('users/<int:pk>', auth_views.UserDetailView.as_view(), name='user-detail'),
    path('users/<int:pk>/toggle-status', auth_views.toggle_user_status, name='toggle-user-status'),

    path('trips/plan', views.plan_trip, name='plan-trip'),
    path('trips', views.TripListCreateView.as_view(), name='trips-list-create'),
    path('trips/<int:pk>', views.TripDetailView.as_view(), name='trip-detail'),

    path('trips/<int:pk>/submit', views.submit_trip, name='submit-trip'),
    path('trips/<int:pk>/approve', views.approve_trip, name='approve-trip'),
    path('trips/<int:pk>/reject', views.reject_trip, name='reject-trip'),
    path('trips/<int:pk>/start', views.start_trip, name='start-trip'),
    path('trips/<int:pk>/complete', views.complete_trip, name='complete-trip'),
    path('trips/<int:pk>/cancel', views.cancel_trip, name='cancel-trip'),

    path('logs', views.LogListView.as_view(), name='logs-list'),
    path('logs/<int:pk>', views.LogDetailView.as_view(), name='log-detail'),
    path('logs/submit', views.submit_logs, name='submit-logs'),
    path('logs/<int:pk>/review', views.review_log, name='review-log'),
]
