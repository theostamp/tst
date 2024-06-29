from django.urls import path
from . import views

urlpatterns = [
    path('upload_json/<str:username>/', views.upload_json, name='upload_json'),
    path('upload_json/products.json', views.products_json, name='products_json'),
    path('list_order_files/<str:tenant>/', views.list_order_files, name='list_order_files'),
    path('get_order/<str:tenant>/<str:filename>/', views.get_order, name='get_order_tenant'),
    path('table_selection/', views.table_selection, name='table_selection'),
    path('tables/table_selection/', views.table_selection, name='table_selection'),
    
    path('order_for_table/<int:table_number>/', views.order_for_table, name='order_for_table'),    
    
    
    path('submit_order/', views.submit_order, name='submit_order'),
    path('order_for_table/<int:table_number>/submit_order/', views.submit_order, name='submit_order_specific'),
    path('success/', views.success, name='success'),
    path('orders_json/', views.get_orders_json, name='get_orders_json'),
    path('get_json/', views.get_json, name='get_json'),
    path('order_summary/', views.order_summary, name='order_summary'),
    path('update_order/', views.update_order, name='update_order'),
    path('order-summary/', views.order_summary, name='order_summary'),
    path('process-orders/', views.process_orders, name='process_orders'),
    path('delete_order_file/<str:filename>/', views.delete_order_file, name='delete_order_file'),
    path('cancel_order/', views.cancel_order, name='cancel_order'),
    path('get-orders/', views.get_orders, name='get-orders'),
    path('delete_received_orders/<str:tenant>/', views.delete_received_orders, name='delete_received_orders'),
    path('signal_refresh_order_summary/', views.signal_refresh_order_summary, name='signal_refresh_order_summary'),
    path('check_for_refresh/', views.check_for_refresh, name='check_for_refresh'),
    path('', views.index, name='index'),
    path('table_selection_with_time_diff/', views.table_selection_with_time_diff, name='table_selection_with_time_diff'),
    path('tenants_folders/<str:tenant>_upload_json/occupied_tables.json', views.get_occupied_tables, name='get_occupied_tables'),
    path('tenants_folders/<str:tenant>_received_orders/<str:filename>/', views.serve_order_file, name='serve_order_file'),
    path('save_positions', views.save_positions, name='save_positions'),
    path('load_positions', views.load_positions, name='load_positions'),
    path('update_time_diff/<str:tenant>/<str:filename>/', views.update_time_diff, name='update_time_diff'),
    path('order_details/', views.order_details, name='order_details'),
    path('test_read_file/', views.test_read_file, name='test_read_file'),
]
