# Warm

## Project Video Link : https://youtu.be/cpPmBlvtdrs

## Requirement
    
[get-pip.zip](https://github.com/7Har/Warm/files/6250009/get-pip.zip)


    pip install --upgrade pip

    pip install django
     
    pip install psycopg2

    pip install pycryptodome

    pip install django-admin-rangefilter
    
    python -m pip install Pillow  

    pip install django-tenants  

    pip install bootstrap4

    pip install djangorestframework
    
    pip install channels

    <!-- pip install daphne -->
    pip install gunicorn
     


     pip install -r requirements.txt
  

## To run the server, run the following command:
        
    python manage.py makemigrations authentication
    python manage.py makemigrations tables
    python manage.py makemigrations tenants
    python manage.py makemigrations
    
    python manage.py migrate tenants
    python manage.py migrate authentication
    python manage.py migrate tables
    python manage.py migrate_schemas
    python manage.py migrate_schemas --shared 
    python manage.py migrate 


    
python manage.py shell

from tenants.models import Tenant, Domain
from django.db import connection

# Δημιουργία ενός δημόσιου ενοικιαστή
tenant = Tenant(name='public_tenant', schema_name='public_tenant')
tenant.save()  # Αυτό θα δημιουργήσει επίσης το σχήμα της βάσης δεδομένων

# Ελέγξτε αν ο ενοικιαστής δημιουργήθηκε επιτυχώς
print(Tenant.objects.all())
from tenants.models import Tenant, Domain

# Ανακτήστε τον ενοικιαστή 'public_tenant'
public_tenant = Tenant.objects.get(name='public_tenant')

# Προσθέστε το domain 'localhost' στον ενοικιαστή 'public_tenant'
Domain.objects.create(domain='localhost', tenant=public_tenant, is_primary=True)

# Επαληθεύστε ότι το νέο domain προστέθηκε σωστά
print(Domain.objects.all())



    python manage.py runserver 8081



python manage.py createsuperuser    
python manage.py create_tenant
python manage.py create_tenant_superuser

python manage.py collectstatic

    daphne -u /tmp/daphne1.sock -b 0.0.0.0 -p 8003 rest_order.asgi:application    





docker system prune -a
docker image prune
docker volume prune

docker-compose logs -f


cd rest_order
git init
git add .
git commit -m "N10"
git remote add origin https://github.com/theostamp/tst.git
git push -u origin main --force

cd rest_order
git add .
git commit -m "ver 1.0.1"
git remote add origin https://github.com/theostamp/tst.git
git push -u origin main