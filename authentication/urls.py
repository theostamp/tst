# rest_order\authentication\urls.py
from django.urls import path
from .views import register, login_view, setup_url, user_credits
from . import views

urlpatterns = [
    path('register/', register, name='register'),
    path('login/', login_view, name='login'),
    path('setup_url/', setup_url, name='setup_url'),
    path('user-credits/', user_credits, name='user_credits'),
    path('', views.home, name='home'),
]

