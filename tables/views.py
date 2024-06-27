import logging
from logging.handlers import RotatingFileHandler
import json
import os
import threading
import time
from datetime import datetime, timedelta
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import DisallowedHost
from django.http import JsonResponse, HttpResponse, Http404, HttpResponseNotFound
from django.shortcuts import render
from django.template.loader import get_template
from django.utils.timezone import localtime, make_aware
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods
from rest_framework.views import APIView  # Εισαγωγή της APIView
from rest_framework.response import Response
from .models import Order, Product
from django.db import connection
from django_tenants.utils import (
    get_public_schema_name,
    get_public_schema_urlconf,
    get_tenant_types,
    has_multi_type_tenants,
    remove_www,
)
from django.urls import set_urlconf
from django.utils.deprecation import MiddlewareMixin
from django.http import JsonResponse, HttpResponseBadRequest

# Ρύθμιση του logging
LOG_FILENAME = 'order_submissions.log'

# Δημιουργία logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Δημιουργία RotatingFileHandler
file_handler = RotatingFileHandler(LOG_FILENAME, maxBytes=5*1024*1024, backupCount=5)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# Προσθήκη του handler στο logger
logger.addHandler(file_handler)

# Δημιουργία console handler για την εμφάνιση logs στην κονσόλα
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(console_handler)

# Έλεγχος αν το αρχείο log υπάρχει και δημιουργία αν δεν υπάρχει
if not os.path.exists(LOG_FILENAME):
    open(LOG_FILENAME, 'a').close()

def index(request):
    return render(request, 'index.html')

@csrf_exempt
def check_for_refresh(request):
    refresh_needed = cache.get('refresh_order_summary', False)
    if refresh_needed:
        cache.delete('refresh_order_summary')
    return JsonResponse({'refresh': refresh_needed})

@csrf_exempt
def signal_refresh_order_summary(request):
    data = json.loads(request.body)
    if data.get('refresh'):
        cache.set('refresh_order_summary', True, timeout=90)  # Θέτει τη σημαία για 60 δευτερόλεπτα
    return JsonResponse({'status': 'success'})

@csrf_exempt
@require_http_methods(["DELETE"])
def delete_received_orders(request, tenant):
    response_data = {
        'checked_files': [],
        'deleted_files': [],
        'not_found_files': [],
        'errors': [],
        'file_paths_checked': [],
        'order_ids_found': []  # Νέα λίστα για τα order_id που βρέθηκαν
    }

    try:
        data = json.loads(request.body)
        order_ids = set(map(str, data.get('order_ids', [])))
        directory = f'tenants_folders/{tenant}_received_orders'

        if not os.path.exists(directory):
            response_data['errors'].append('Directory not found.')
            return JsonResponse(response_data, status=404)

        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            response_data['checked_files'].append(filename)
            response_data['file_paths_checked'].append(file_path)

            with open(file_path, 'r') as file:
                try:
                    file_data = json.load(file)
                    file_order_id = str(file_data.get('order_id'))
                    response_data['order_ids_found'].append(file_order_id)  # Καταγραφή του order_id από το αρχείο
                except json.JSONDecodeError:
                    continue

                if file_order_id in order_ids:
                    os.remove(file_path)
                    response_data['deleted_files'].append(filename)
                else:
                    response_data['not_found_files'].append(filename)

        return JsonResponse({'message': 'Files processed successfully.', **response_data})
    except Exception as e:
        response_data['errors'].append(str(e))
        return JsonResponse(response_data, status=500)

@csrf_exempt
def upload_json(request, username):
    tenant_folder = f'/tenants_folders/{username}_upload_json'
    os.makedirs(tenant_folder, exist_ok=True)

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            # Προσθήκη χειρισμού για το 'occupied_tables'
            file_type = next((k for k in data if k in ['products', 'tables', 'occupied_tables']), None)
            if not file_type:
                return JsonResponse({'status': 'error', 'message': 'Unknown file type'}, status=400)

            # Μετονομασία κλειδιού 'tables' σε 'occupied_tables' κατά την αποθήκευση
            file_name = f"{file_type.replace('tables', 'occupied_tables')}.json"
            file_path = os.path.join(tenant_folder, file_name)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            with open(file_path, 'w') as file:
                json.dump(data[file_type], file, indent=4)

            return JsonResponse({'status': 'success'})
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON data'}, status=400)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)

def table_selection(request):
    """
    Επιστρέφει μια λίστα με τα τραπέζια από το αρχείο occupied_tables.json
    και τα εμφανίζει σε μια σελίδα επιλογής τραπεζιού.
    """
    tenant = connection.get_tenant()
    tenant_name = tenant.name

    occupied_tables_file = os.path.join(settings.BASE_DIR, 'tenants_folders', f'{tenant_name}_upload_json', 'occupied_tables.json')

    try:
        with open(occupied_tables_file, 'r') as file:
            tables_data = json.load(file)
            return render(request, 'tables/table_selection.html', {'tables': tables_data})
    except FileNotFoundError:
        # Εδώ μπορείτε να χειριστείτε την περίπτωση που το αρχείο δεν βρίσκεται
        return HttpResponseNotFound('File not found')

@csrf_exempt
def order_for_table(request, table_number):
    """
    Επεξεργάζεται και εμφανίζει τις πληροφορίες παραγγελίας για ένα συγκεκριμένο τραπέζι,
    διαχωρίζοντας τα προϊόντα ανά κατηγορία.
    """
    schema_name = connection.get_schema()
    username = connection.get_tenant()
    # Φόρτωση δεδομένων από το JSON αρχείο
    products_file_path = os.path.join(settings.BASE_DIR, 'tenants_folders', f'{username}_upload_json', 'products.json')
    with open(products_file_path, 'r') as file:
        products_data = json.load(file)
        categorized_products = {}
    for product in products_data:
        category = product['category']
        if category not in categorized_products:
            categorized_products[category] = []
        categorized_products[category].append(product)

    # Πάρτε μόνο τις πρώτες τρεις κατηγορίες
    first_three_categories = dict(list(categorized_products.items())[:3])
    return render(request, 'tables/order_for_table.html', {'table_number': table_number, 'categories': first_three_categories})




def success(request):
    return render(request, 'tables/success.html')


@csrf_exempt
def list_order_files(request, tenant):
    """
    Επιστρέφει ένα JSON απόκριση με τη λίστα των αρχείων παραγγελίας
    που βρίσκονται σε έναν συγκεκριμένο φάκελο για τον δεδομένο tenant.
    """
    folder_path = os.path.join(settings.BASE_DIR, 'tenants_folders', f'{tenant}_received_orders')

    if os.path.exists(folder_path):
        file_list = os.listdir(folder_path)
        return JsonResponse({'files': file_list})
    else:
        return JsonResponse({'status': 'error', 'message': 'Directory not found'}, status=404)

def serve_order_file(request, tenant, filename):
    folder_path = os.path.join(settings.BASE_DIR, 'tenants_folders', f'{tenant}_received_orders')
    file_path = os.path.join(folder_path, filename)
    
    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            data = json.load(file)
            return JsonResponse(data)
    else:
        return HttpResponseNotFound('File not found')

@csrf_exempt
def get_order(request, tenant, filename):
    """
    Επιστρέφει τα περιεχόμενα ενός συγκεκριμένου JSON αρχείου παραγγελίας
    για τον δοθέν tenant με βάση το όνομα αρχείου που παρέχεται.
    """
    file_path = os.path.join(settings.BASE_DIR, 'tenants_folders', f'{tenant}_received_orders', filename)
    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            data = json.load(file)
            return HttpResponse(json.dumps(data), content_type='application/json')
    else:
        raise Http404("Το αρχείο δεν βρέθηκε")

@csrf_exempt
def update_product_status(request):
    """
    Λαμβάνει δεδομένα μέσω POST και ενημερώνει την κατάσταση ενός προϊόντος
    σε ένα JSON αρχείο, βάσει του μοναδικού κωδικού προϊόντος.
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            print("Ληφθέντα δεδομένα:", data)  # Εκτύπωση των δεδομένων για επαλήθευση
            unique_product_id = data.get('uniqueProductId')
            order_done = data.get('order_done')
            table_number = data.get('table_number')  # Προσθήκη του table_number
            quantity = data.get('quantity')  # Προσθήκη του quantity

            product_id, time_id = unique_product_id.rsplit('-', 1)

            product_data = {
                "product_id": product_id,
                "time_id": time_id,
                "order_done": order_done,
                "table_number": table_number,  # Ενσωμάτωση του table_number
                "quantity": quantity  # Ενσωμάτωση του quantity
            }
            print(product_data)
            folder_name = "orders_completed"
            file_name = f"updated_product_status_{unique_product_id}.json"
            folder_path = os.path.join('rest_order', folder_name)
            file_path = os.path.join(folder_path, file_name)

            os.makedirs(folder_path, exist_ok=True)

            with open(file_path, 'w') as file:
                json.dump(product_data, file)
                logger.info(f"Δημιουργία αρχείου: {file_path}")

            return JsonResponse({'status': 'success'})
        except json.JSONDecodeError as e:
            logger.error(f"Σφάλμα JSON Decode: {e}")
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
        except Exception as e:
            logger.error(f"Γενικό σφάλμα: {e}")
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    else:
        logger.error("Λάθος μέθοδος αιτήματος")
        return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)

@csrf_exempt
def list_orders(request):
    """
    Επεξεργάζεται τα αρχεία παραγγελιών και δημιουργεί μια λίστα
    ανά τραπέζι από τις παραγγελίες.
    """
    orders_by_table = {}
    folder_path = 'received_orders'  # Διορθώστε τη διαδρομή ανάλογα

    for filename in os.listdir(folder_path):
        if filename.endswith('.json'):
            with open(os.path.join(folder_path, filename), 'r') as file:
                order = json.load(file)
                table_number = order['table_number']

                if table_number not in orders_by_table:
                    orders_by_table[table_number] = {
                        'orders': [], 'waiter': order.get('waiter'), 'table_number': table_number}  # Προσθήκη του table_number εδώ

                orders_by_table[table_number]['orders'].append(order)

    return render(request, 'tables/list_orders.html', {'orders_by_table': orders_by_table})

@csrf_exempt
def get_orders_json(request):
    """
    Συλλέγει όλες τις παραγγελίες από τα JSON αρχεία σε έναν φάκελο
    και τις επιστρέφει ως μια λίστα σε JSON απόκριση.
    """
    print("Η συνάρτηση get_orders_json κλήθηκε.")
    orders = []
    folder_path = 'received_orders'  # Ενημερώστε με τη σωστή διαδρομή

    print("Ξεκινώντας την επεξεργασία του φακέλου:", folder_path)

    for filename in os.listdir(folder_path):
        if filename.endswith('.json'):
            file_path = os.path.join(folder_path, filename)
            
            print(f"Επεξεργασία αρχείου: {file_path}")

            with open(file_path, 'r') as file:
                orders.append(json.load(file))

    print("Η επεξεργασία του φακέλου ολοκληρώθηκε.")
    return JsonResponse({'orders': orders})

@csrf_exempt
def get_json(request):
    """
    Επιστρέφει μια λίστα αρχείων σε JSON μορφή από έναν συγκεκριμένο φάκελο.
    """
    folder_path = os.path.join(settings.BASE_DIR, 'received_orders')
    if os.path.exists(folder_path):
        file_list = os.listdir(folder_path)
        return JsonResponse({'files': file_list})
    else:
        return JsonResponse({'status': 'error', 'message': 'Directory not found'}, status=404)

@csrf_exempt
def products_json(request):
    """
    Φορτώνει και επιστρέφει τα δεδομένα προϊόντων από ένα JSON αρχείο.
    """
    with open(os.path.join(settings.BASE_DIR, 'upload_json', 'products.json'), 'r') as file:
        data = json.load(file)
        return JsonResponse(data)

@csrf_exempt
def process_orders(folder_path, output_file):
    """
    Επεξεργάζεται τα αρχεία παραγγελιών σε έναν φάκελο και τα αποθηκεύει
    συγκεντρωτικά σε ένα αρχείο output.
    """
     # Έλεγχος αν ο φάκελος υπάρχει και δημιουργία εάν δεν υπάρχει
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)

    all_orders = []
    unique_order_ids = set()

# Επεξεργασία νέων αρχείων JSON από το folder_path
    for filename in os.listdir(folder_path):
        if filename.endswith('.json'):
            file_path = os.path.join(folder_path, filename)
            try:
                with open(file_path, 'r') as file:
                    order_data = json.load(file)

                    # Έλεγχος αν το διαβασμένο είναι λεξικό και μετατροπή σε λίστα
                    if isinstance(order_data, dict):
                        order_data = [order_data]

                    for order in order_data:
                        # Προστασία για περίπτωση που η εγγραφή δεν είναι λεξικό
                        if not isinstance(order, dict):
                            continue

                        order_id = order.get('order_id')
                        if order_id and order_id not in unique_order_ids:
                            unique_order_ids.add(order_id)
                            all_orders.append(order)
            except Exception as e:
                print(f"Προέκυψε σφάλμα κατά την επεξεργασία του αρχείου {filename}: {e}")
    # Αποθήκευση των ενημερωμένων παραγγελιών στο output_file
    with open(output_file, 'w') as file:
        json.dump(all_orders, file)

def order_summary(request):
    schema_name = connection.get_schema()
    tenant = connection.get_tenant()
    products_dict = load_products(tenant)
    folder_path = os.path.join(settings.BASE_DIR, 'tenants_folders', f'{tenant.name}_received_orders')

    if not os.path.exists(folder_path):
        context = {'error_message': f"Σφάλμα: Ο φάκελος {folder_path} δεν υπάρχει"}
        return render(request, 'tables/error_page.html', context)

    current_time = datetime.now()
    orders_by_table = {}
    processed_order_ids = set()

    for filename in os.listdir(folder_path):
        if filename.endswith('.json'):
            file_path = os.path.join(folder_path, filename)
            try:
                with open(file_path, 'r') as file:
                    order = json.load(file)
                
                order_id = order.get('order_id')
                if order_id in processed_order_ids:
                    continue

                processed_order_ids.add(order_id)

                if order.get('order_done') == 0:
                    table_number = order['table_number']
                    if table_number not in orders_by_table:
                        orders_by_table[table_number] = {'orders': [], 'waiter': order.get('waiter')}

                    order_time_str = order.get('timestamp')
                    if order_time_str:
                        order_time = datetime.strptime(order['timestamp'], "%Y-%m-%d %H:%M:%S")
                        if order_time > current_time:
                            order_time -= timedelta(days=1)
                        time_passed = current_time - order_time
                        order['time_passed'] = int(time_passed.total_seconds() // 60)
                        order['time_diff'] = order['time_passed']  # Ενημέρωση του time_diff με το time_passed

                        # Ενημέρωση του αρχείου JSON με το ενημερωμένο time_diff
                        with open(file_path, 'w') as update_file:
                            json.dump(order, update_file, indent=4)
                    else:
                        order['time_passed'] = 'Άγνωστος χρόνος'

                    for product in order.get('products', []):
                        product_id = str(product['id'])
                        product_info = products_dict.get(product_id, {})
                        product['name'] = product_info.get('description', 'Unknown Product')
                    
                    orders_by_table[table_number]['orders'].append(order)

            except json.JSONDecodeError as e:
                print(f"Σφάλμα κατά την ανάγνωση του JSON: {e}")
                continue

    # Ταξινόμηση των τραπεζιών βάσει του μεγαλύτερου χρόνου αναμονής
    sorted_orders_by_table = dict(sorted(orders_by_table.items(), key=lambda item: max(order['time_passed'] if isinstance(order['time_passed'], int) else 0 for order in item[1]['orders']), reverse=True))

    return render(request, 'tables/order_summary.html', {'sorted_orders_by_table': sorted_orders_by_table})

@csrf_exempt
def load_products(tenant):
    tenant_folder = os.path.join(settings.BASE_DIR, 'tenants_folders', f'{tenant.name}_upload_json')
    products_file = os.path.join(tenant_folder, 'products.json')

    if not os.path.exists(products_file):
        return {}

    with open(products_file, 'r') as file:
        products_data = json.load(file)
        return {str(product['id']): product for product in products_data}

@csrf_exempt
def submit_order(request, table_number=None):
    tenant = connection.get_tenant()
    products_dict = load_products(tenant)
    
    if request.method == 'POST':
        try:
            order_data = json.loads(request.body)
            current_time = datetime.now()
            order_id_base = int(current_time.strftime("%H%M%S"))
            products = order_data.get('products', [])

            for index, product in enumerate(products, start=1):
                product_order_id = f"{order_id_base}{index}"
                product_info = products_dict.get(str(product['id']))
                if product_info:
                    description = product_info['description']
                    price = product_info['price']

                    timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S")
                    new_order_data = {
                        'table_number': order_data['table_number'],
                        'product_description': description,
                        'quantity': product['quantity'],
                        'total_cost': price * int(product['quantity']),
                        'waiter': order_data.get('waiter', 'unknown'),
                        'order_done': False,
                        'printed': False,
                        'order_id': product_order_id,
                        'timestamp': timestamp
                    }

                    filename = f"order_table_{table_number}_{product_order_id}.json"
                
                    # Χρήση της χρονικής διαφοράς κατά την ανάκτηση
                    time_diff = int((datetime.now() - datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")).total_seconds() // 60)
                    new_order_data['time_diff'] = time_diff

                # Εδώ χρησιμοποιούμε το όνομα του tenant για να δημιουργήσουμε το σωστό μονοπάτι
                folder_path = os.path.join(settings.BASE_DIR, 'tenants_folders', f'{tenant.name}_received_orders')
                file_path = os.path.join(folder_path, filename)

                if not os.path.exists(folder_path):
                    os.makedirs(folder_path)

                with open(file_path, 'w') as file:
                    json.dump(new_order_data, file)

            return JsonResponse({'status': 'success', 'message': 'Η παραγγελία υποβλήθηκε με επιτυχία'})
        except Exception as e:
            logging.error(f"Γενικό σφάλμα: {e}")
            return JsonResponse({'status': 'error', 'message': str(e)})

    return JsonResponse({'status': 'error', 'message': 'Μη έγκυρο αίτημα'})


@csrf_exempt
def update_order_status_in_json(order_id, new_status=1):
    """
    Ενημερώνει την κατάσταση μιας παραγγελίας σε ένα κεντρικό JSON αρχείο
    με βάση το μοναδικό κωδικό της παραγγελίας.
    """
    file_path = 'all_orders.json'

    try:
        with open(file_path, 'r') as file:
            orders = json.load(file)

        order_found = False
        for order in orders:
            # Βρείτε την παραγγελία με βάση το order_id
            if str(order.get('order_id')) == str(order_id):
                print(f"Updating order with ID: {order_id}")
                order['order_done'] = new_status
                order_found = True
                break

        if not order_found:
            print(f"Order with ID: {order_id} not found")
            return False, "Order not found"

        with open(file_path, 'w') as file:
            json.dump(orders, file, indent=4)

        return True, "Order updated successfully"

    except Exception as e:
        print(f"Error in update_order_status_in_json: {e}")
        return False, str(e)
    
def update_order_status_in_folder(order_id, new_status=1, folder_path=None):
    try:
        # Ανάκτηση του τρέχοντος tenant εάν δεν δίνεται folder_path
        if folder_path is None:
            tenant = connection.get_tenant()
            tenant_name = tenant.name
            folder_path = os.path.join(settings.BASE_DIR, 'tenants_folders', f'{tenant_name}_received_orders')

        order_found = False
        for filename in os.listdir(folder_path):
            if filename.endswith('.json'):
                file_path = os.path.join(folder_path, filename)
                with open(file_path, 'r') as file:
                    order = json.load(file)

                if str(order.get('order_id')) == str(order_id):
                    print(f"Updating order with ID: {order_id}")
                    order['order_done'] = new_status
                    order_found = True

                    with open(file_path, 'w') as file:
                        json.dump(order, file, indent=4)
                    break

        if not order_found:
            print(f"Order with ID: {order_id} not found")
            return False, "Order not found"

        return True, "Order updated successfully"

    except Exception as e:
        print(f"Error in update_order_status_in_folder: {e}")
        return False, str(e)

@csrf_exempt
def update_order(request):
    try:
        data = json.loads(request.body)
        print(f"Received data: {data}")

        if not isinstance(data, list):
            raise ValueError("Invalid data format: expected a list of orders")

        for order in data:
            order_id = order.get('order_id')
            if not order_id:
                raise ValueError("No order_id provided in one of the orders")

            new_status = order.get('order_done', 1)
            print(f"Order ID: {order_id}, New Status: {new_status}")

            success, message = update_order_status_in_folder(order_id, new_status)
            if not success:
                print(f"Order update failed for {order_id}: {message}")

        return JsonResponse({"success": True})
    except json.JSONDecodeError as e:
        print(f"JSON Decode Error: {e}")
        return JsonResponse({"success": False, "error": "Invalid JSON data"}, status=400)
    except Exception as e:
        print(f"General error in update_order: {e}")
        return JsonResponse({"success": False, "error": str(e)}, status=500)

@csrf_exempt
def delete_order_file(request, filename):
    if request.method == 'DELETE':
        # Ανάκτηση του τρέχοντος tenant
        tenant = connection.get_tenant()
        tenant_name = tenant.name

        # Δημιουργία της σωστής διαδρομής με βάση το όνομα του tenant
        file_path = os.path.join(settings.BASE_DIR, 'tenants_folders', f'{tenant_name}_received_orders', filename)

        if os.path.exists(file_path):
            os.remove(file_path)
            return JsonResponse({'status': 'success', 'message': 'File deleted successfully'})
        else:
            return JsonResponse({'status': 'error', 'message': 'File not found'}, status=404)

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)

@csrf_exempt
def cancel_order(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)

            # Ανάκτηση του τρέχοντος tenant
            tenant = connection.get_tenant()
            tenant_name = tenant.name

            # Καθορισμός του σωστού φακέλου με βάση τον tenant
            folder_path = os.path.join(settings.BASE_DIR, 'tenants_folders', f'{tenant_name}_received_orders')

            for order in data:
                order_id = order.get('order_id')

                # Αναζήτηση και διαγραφή των αρχείων που περιέχουν το order_id
                for filename in os.listdir(folder_path):
                    if filename.endswith('.json') and order_id in filename:
                        file_path = os.path.join(folder_path, filename)
                        os.remove(file_path)
                        break  # Βγείτε από το loop μετά την εύρεση και διαγραφή του αρχείου

            return JsonResponse({'status': 'success', 'message': 'Οι παραγγελίες ακυρώθηκαν'})

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})

    else:
        return JsonResponse({'status': 'error', 'message': 'Μη έγκυρη μέθοδος αιτήματος'})

@csrf_exempt
def get_orders(request):
    # Λογική για την ανάκτηση δεδομένων των παραγγελιών
    orders = Order.objects.all()  # ή οποιαδήποτε άλλη λογική για ανάκτηση παραγγελιών
    order_data = [{'order_id': order.id, 'product_description': order.product_description, 'quantity': order.quantity, 'timestamp': order.timestamp} for order in orders]
    
    return JsonResponse(order_data, safe=False)

def table_selection_with_time_diff(request):
    tenant = connection.get_tenant()
    tenant_name = tenant.name

    occupied_tables_file = os.path.join(settings.BASE_DIR, 'tenants_folders', f'{tenant_name}_upload_json', 'occupied_tables.json')

    if not os.path.exists(occupied_tables_file):
        logger.error(f"Occupied tables file not found: {occupied_tables_file}")
        return HttpResponseNotFound(f'Occupied tables file not found: {occupied_tables_file}')

    try:
        with open(occupied_tables_file, 'r') as file:
            tables_data = json.load(file)

            for table in tables_data:
                table_number = table['table_number']
                time_diff = get_time_diff_from_file(tenant_name, table_number)
                table['time_diff'] = time_diff

            return render(request, 'tables/table_selection_with_time_diff.html', {'tables': tables_data})
    except FileNotFoundError:
        logger.error(f"File not found: {occupied_tables_file}")
        return HttpResponseNotFound('File not found')
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from {occupied_tables_file}: {e}")
        return HttpResponseNotFound('Error decoding JSON file')

def get_time_diff_from_file(tenant_name, table_number):
    folder_path = os.path.join(settings.BASE_DIR, 'tenants_folders', f'{tenant_name}_received_orders')

    if not os.path.exists(folder_path):
        logger.error(f"Received orders folder not found: {folder_path}")
        return 'N/A'

    for filename in sorted(os.listdir(folder_path)):
        if filename.endswith('.json') and f"order_table_{table_number}_" in filename:
            file_path = os.path.join(folder_path, filename)
            try:
                with open(file_path, 'r') as file:
                    order_data = json.load(file)
                    time_diff = order_data.get('time_diff')
                    if time_diff is not None:
                        hours, minutes = divmod(time_diff, 60)
                        return f"{int(hours):02}:{int(minutes):02}"
            except json.JSONDecodeError as e:
                logger.error(f"Error decoding JSON from {file_path}: {e}")
                continue
            except Exception as e:
                logger.error(f"Error reading file {file_path}: {e}")
                continue

    return 'N/A'

def get_occupied_tables(request, tenant):
    tenant_folder = os.path.join(settings.BASE_DIR, 'tenants_folders', f'{tenant}_upload_json')
    file_path = os.path.join(tenant_folder, 'occupied_tables.json')

    if not os.path.exists(file_path):
        return HttpResponseNotFound('File not found')

    with open(file_path, 'r') as file:
        data = json.load(file)
    return JsonResponse(data, safe=False)

@csrf_exempt
def save_positions(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            positions_file_path = os.path.join(settings.BASE_DIR, 'button_positions.json')
            with open(positions_file_path, 'w') as file:
                json.dump(data, file, indent=4)
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)

@csrf_exempt
def load_positions(request):
    try:
        positions_file_path = os.path.join(settings.BASE_DIR, 'button_positions.json')
        if os.path.exists(positions_file_path):
            with open(positions_file_path, 'r') as file:
                data = json.load(file)
                return JsonResponse(data)
        else:
            return JsonResponse({})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
def update_time_diff(request, tenant, filename):
    if request.method == 'POST':
        try:
            print(f"Received request to update time_diff for tenant: {tenant}, file: {filename}")

            # Διαδρομή στο αρχείο JSON που χρειάζεται ενημέρωση
            file_path = os.path.join('/app/tenants_folders', f'{tenant}_received_orders', filename)
            print(f"File path: {file_path}")

            # Ελέγξτε αν το αρχείο υπάρχει
            if not os.path.exists(file_path):
                print("File not found")
                return HttpResponseBadRequest("File not found")

            # Διαβάστε τα δεδομένα του αρχείου JSON
            with open(file_path, 'r') as file:
                order_data = json.load(file)
            print(f"Current order data: {order_data}")

            # Ενημερώστε το time_diff με βάση τα δεδομένα που έχουν σταλεί στο αίτημα
            if 'time_diff' in request.POST:
                time_diff = request.POST['time_diff']
                order_data['time_diff'] = time_diff
                print(f"Updated time_diff to: {time_diff}")
            else:
                print("time_diff not found in POST data")
                return HttpResponseBadRequest("time_diff not found in POST data")

            # Αποθηκεύστε τα ενημερωμένα δεδομένα πίσω στο αρχείο JSON
            with open(file_path, 'w') as file:
                json.dump(order_data, file)
            print("File updated successfully")

            return JsonResponse({"status": "success"})
        except json.JSONDecodeError as json_error:
            print(f"JSON decode error: {json_error}")
            return HttpResponseBadRequest(f"JSON decode error: {json_error}")
        except Exception as e:
            print(f"Exception occurred: {e}")
            return HttpResponseBadRequest(str(e))
    else:
        print("Invalid request method")
        return HttpResponseBadRequest("Invalid request method")


def order_details(request):
    table_number = request.GET.get('table')
    tenant = request.GET.get('tenant')

    # Διαδρομή στο αρχείο JSON που περιέχει τα δεδομένα της παραγγελίας
    file_path = os.path.join('tenants_folders', f'{tenant}_received_orders', f'order_table_{table_number}.json')
    
    try:
        with open(file_path, 'r') as file:
            order_data = json.load(file)
    except FileNotFoundError:
        order_data = {'items': []}

    return render(request, 'tables/order_details.html', {'order_data': order_data, 'table_number': table_number})
