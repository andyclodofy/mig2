#!/usr/bin/env python3
"""
Script de prueba para diagnosticar el problema de bloqueo con crm.lead
"""
import xmlrpc.client
import os
from dotenv import load_dotenv

load_dotenv()

# Configuración
url = os.getenv('V18_URL', 'http://localhost:8069')
db = os.getenv('V18_DB', 'odoo18')
username = os.getenv('V18_USERNAME', 'admin')
password = os.getenv('V18_PASSWORD', 'admin')

print(f"Conectando a {url} (DB: {db})...")

# Conectar
common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common', allow_none=True)
uid = common.authenticate(db, username, password, {})

if not uid:
    print("ERROR: No se pudo autenticar")
    exit(1)

print(f"✓ Autenticado como UID {uid}")

models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object', allow_none=True)

# Prueba 1: Leer un registro de crm.lead
print("\n--- Prueba 1: Leer crm.lead ---")
try:
    leads = models.execute_kw(db, uid, password, 'crm.lead', 'search_read', [[]], {'limit': 1, 'fields': ['name', 'id']})
    print(f"✓ Lectura exitosa: {leads}")
except Exception as e:
    print(f"✗ Error en lectura: {e}")

# Prueba 2: Crear UN SOLO registro simple
print("\n--- Prueba 2: Crear UN registro de crm.lead ---")
test_record = {
    'name': 'TEST - Prueba de migración',
    'type': 'opportunity',
}

print(f"Enviando: {test_record}")
try:
    import time
    start = time.time()
    result = models.execute_kw(db, uid, password, 'crm.lead', 'create', [[test_record]])
    elapsed = time.time() - start
    print(f"✓ Creación exitosa en {elapsed:.2f}s: ID = {result}")
    
    # Eliminar el registro de prueba
    print(f"Eliminando registro de prueba ID {result[0]}...")
    models.execute_kw(db, uid, password, 'crm.lead', 'unlink', [result])
    print("✓ Registro eliminado")
except Exception as e:
    print(f"✗ Error en creación: {e}")

# Prueba 3: Crear 5 registros a la vez
print("\n--- Prueba 3: Crear 5 registros de crm.lead ---")
test_records = [{'name': f'TEST - Migración {i}', 'type': 'opportunity'} for i in range(5)]

print(f"Enviando: {len(test_records)} registros")
try:
    import time
    start = time.time()
    result = models.execute_kw(db, uid, password, 'crm.lead', 'create', [test_records])
    elapsed = time.time() - start
    print(f"✓ Creación exitosa en {elapsed:.2f}s: IDs = {result}")
    
    # Eliminar los registros de prueba
    print(f"Eliminando {len(result)} registros de prueba...")
    models.execute_kw(db, uid, password, 'crm.lead', 'unlink', [result])
    print("✓ Registros eliminados")
except Exception as e:
    print(f"✗ Error en creación: {e}")

# Prueba 4: Crear registro con datos reales del script de migración
print("\n--- Prueba 4: Crear registro con datos reales ---")
real_record = {
    "name": "PARTNER",
    "partner_id": 146714,
    "active": True,
    "website": "https://www.cips.it/",
    "team_id": 31,
    "contact_name": "Giovani Zanasca",
    "partner_name": "Cips Informatica",
    "type": "opportunity",
    "priority": "3",
    "stage_id": 8,
    "user_id": 670,
    "probability": 100,
    "expected_revenue": 50,
    "date_deadline": "2019-05-26",
    "color": 0,
    "street": "Via G. Marconi, 18. . Città di Castello . PG",
    "zip": "06012",
    "city": "Peruggia",
    "phone": "+39 (0)75 8521413",
    "mobile": "39 349 1992152",
    "message_bounce": 0
}

print(f"Enviando: {real_record}")
try:
    import time
    start = time.time()
    result = models.execute_kw(db, uid, password, 'crm.lead', 'create', [[real_record]])
    elapsed = time.time() - start
    print(f"✓ Creación exitosa en {elapsed:.2f}s: ID = {result}")
    
    # Eliminar el registro de prueba
    print(f"Eliminando registro de prueba...")
    models.execute_kw(db, uid, password, 'crm.lead', 'unlink', [result])
    print("✓ Registro eliminado")
except Exception as e:
    print(f"✗ Error en creación: {e}")

# Prueba 5: Probar sin los campos many2one
print("\n--- Prueba 5: Crear registro SIN campos many2one (partner_id, team_id, stage_id, user_id) ---")
simple_record = {
    "name": "TEST - Sin many2one",
    "active": True,
    "website": "https://www.cips.it/",
    "contact_name": "Giovani Zanasca",
    "partner_name": "Cips Informatica",
    "type": "opportunity",
    "priority": "3",
    "probability": 100,
    "expected_revenue": 50,
    "date_deadline": "2019-05-26",
    "color": 0,
    "street": "Via G. Marconi, 18",
    "zip": "06012",
    "city": "Peruggia",
    "phone": "+39 123456789",
    "mobile": "39 349 1992152",
    "message_bounce": 0
}

print(f"Enviando: {simple_record}")
try:
    import time
    start = time.time()
    result = models.execute_kw(db, uid, password, 'crm.lead', 'create', [[simple_record]])
    elapsed = time.time() - start
    print(f"✓ Creación exitosa en {elapsed:.2f}s: ID = {result}")
    
    # Eliminar el registro de prueba
    print(f"Eliminando registro de prueba...")
    models.execute_kw(db, uid, password, 'crm.lead', 'unlink', [result])
    print("✓ Registro eliminado")
except Exception as e:
    print(f"✗ Error en creación: {e}")

print("\n✓ Pruebas completadas")

