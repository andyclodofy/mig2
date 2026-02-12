#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para investigar las diferencias entre contract.contract (v13) y sale.subscription (v18)
y entre contract.line (v13) y sale.subscription.line (v18)
"""

import os
import json
from dotenv import load_dotenv
from migrate import OdooConnection

load_dotenv()

# Conectar a ambas versiones
v13_url = os.getenv('V13_URL', 'https://erp.datos101.com')
v13_db = os.getenv('V13_DB', 'd101')
v13_username = os.getenv('V13_USERNAME', 'lorena.perez@clodofy.com')
v13_password = os.getenv('V13_PASSWORD', '')

v18_url = os.getenv('V18_URL', 'http://localhost:8069')
v18_db = os.getenv('V18_DB', '105')
v18_username = os.getenv('V18_USERNAME', 'admin')
v18_password = os.getenv('V18_PASSWORD', 'admin')

v13_conn = OdooConnection(v13_url, v13_db, v13_username, v13_password)
v18_conn = OdooConnection(v18_url, v18_db, v18_username, v18_password)

print("=" * 80)
print("INVESTIGACIÓN: contract.contract (v13) -> sale.subscription (v18)")
print("=" * 80)

# 1. Obtener campos de contract.contract (v13)
print("\n1. CAMPOS DE contract.contract (v13)")
print("-" * 80)
v13_contract_fields = v13_conn.get_fields('contract.contract')
v13_stored_fields = {}
v13_required_fields = []
for field_name, field_info in v13_contract_fields.items():
    if field_info.get('store', True):
        v13_stored_fields[field_name] = field_info
        if field_info.get('required', False):
            v13_required_fields.append(field_name)

print(f"Total campos almacenados: {len(v13_stored_fields)}")
print(f"Campos requeridos: {v13_required_fields}")

# 2. Obtener campos de sale.subscription (v18)
print("\n2. CAMPOS DE sale.subscription (v18)")
print("-" * 80)
v18_subscription_fields = v18_conn.get_fields('sale.subscription')
v18_stored_fields = {}
v18_required_fields = []
for field_name, field_info in v18_subscription_fields.items():
    if field_info.get('store', True):
        v18_stored_fields[field_name] = field_info
        if field_info.get('required', False):
            v18_required_fields.append(field_name)

print(f"Total campos almacenados: {len(v18_stored_fields)}")
print(f"Campos requeridos: {v18_required_fields}")

# 3. Comparar campos
print("\n3. COMPARACIÓN DE CAMPOS")
print("-" * 80)

# Campos comunes
common_fields = set(v13_stored_fields.keys()) & set(v18_stored_fields.keys())
print(f"\nCampos comunes ({len(common_fields)}):")
for field in sorted(common_fields):
    v13_type = v13_stored_fields[field].get('type', 'unknown')
    v18_type = v18_stored_fields[field].get('type', 'unknown')
    if v13_type != v18_type:
        print(f"  ⚠ {field}: v13={v13_type}, v18={v18_type}")
    else:
        print(f"  ✓ {field}: {v13_type}")

# Campos solo en v13
only_v13 = set(v13_stored_fields.keys()) - set(v18_stored_fields.keys())
print(f"\nCampos solo en v13 ({len(only_v13)}):")
for field in sorted(only_v13):
    field_type = v13_stored_fields[field].get('type', 'unknown')
    print(f"  - {field} ({field_type})")

# Campos solo en v18
only_v18 = set(v18_stored_fields.keys()) - set(v13_stored_fields.keys())
print(f"\nCampos solo en v18 ({len(only_v18)}):")
for field in sorted(only_v18):
    field_type = v18_stored_fields[field].get('type', 'unknown')
    required = " [REQUERIDO]" if field in v18_required_fields else ""
    print(f"  - {field} ({field_type}){required}")

# 4. Obtener registros de ejemplo
print("\n4. REGISTROS DE EJEMPLO")
print("-" * 80)

# Obtener algunos contratos de v13
v13_contracts = v13_conn.search_read('contract.contract', [], ['id', 'name', 'partner_id', 'date_start', 'date_end', 'code', 'company_id'], limit=5)
print(f"\nEjemplos de contract.contract (v13):")
for contract in v13_contracts:
    print(f"  ID={contract.get('id')}: {contract.get('name', 'N/A')} (Partner: {contract.get('partner_id', 'N/A')})")

# Obtener algunos subscriptions de v18 (si existen)
v18_subscriptions = v18_conn.search_read('sale.subscription', [], ['id', 'name', 'partner_id', 'date_start', 'code', 'company_id'], limit=5)
print(f"\nEjemplos de sale.subscription (v18): {len(v18_subscriptions)} encontrados")
if v18_subscriptions:
    for sub in v18_subscriptions:
        print(f"  ID={sub.get('id')}: {sub.get('name', 'N/A')} (Partner: {sub.get('partner_id', 'N/A')})")

# 5. Investigar líneas
print("\n" + "=" * 80)
print("INVESTIGACIÓN: contract.line (v13) -> sale.subscription.line (v18)")
print("=" * 80)

# Campos de contract.line (v13)
print("\n5. CAMPOS DE contract.line (v13)")
print("-" * 80)
v13_line_fields = v13_conn.get_fields('contract.line')
v13_line_stored = {}
v13_line_required = []
for field_name, field_info in v13_line_fields.items():
    if field_info.get('store', True):
        v13_line_stored[field_name] = field_info
        if field_info.get('required', False):
            v13_line_required.append(field_name)

print(f"Total campos almacenados: {len(v13_line_stored)}")
print(f"Campos requeridos: {v13_line_required}")

# Campos de sale.subscription.line (v18)
print("\n6. CAMPOS DE sale.subscription.line (v18)")
print("-" * 80)
v18_line_fields = v18_conn.get_fields('sale.subscription.line')
v18_line_stored = {}
v18_line_required = []
for field_name, field_info in v18_line_fields.items():
    if field_info.get('store', True):
        v18_line_stored[field_name] = field_info
        if field_info.get('required', False):
            v18_line_required.append(field_name)

print(f"Total campos almacenados: {len(v18_line_stored)}")
print(f"Campos requeridos: {v18_line_required}")

# Comparar líneas
print("\n7. COMPARACIÓN DE LÍNEAS")
print("-" * 80)

common_line_fields = set(v13_line_stored.keys()) & set(v18_line_stored.keys())
print(f"\nCampos comunes en líneas ({len(common_line_fields)}):")
for field in sorted(common_line_fields):
    v13_type = v13_line_stored[field].get('type', 'unknown')
    v18_type = v18_line_stored[field].get('type', 'unknown')
    if v13_type != v18_type:
        print(f"  ⚠ {field}: v13={v13_type}, v18={v18_type}")
    else:
        print(f"  ✓ {field}: {v13_type}")

only_v13_line = set(v13_line_stored.keys()) - set(v18_line_stored.keys())
print(f"\nCampos solo en contract.line (v13) ({len(only_v13_line)}):")
for field in sorted(only_v13_line):
    field_type = v13_line_stored[field].get('type', 'unknown')
    print(f"  - {field} ({field_type})")

only_v18_line = set(v18_line_stored.keys()) - set(v13_line_stored.keys())
print(f"\nCampos solo en sale.subscription.line (v18) ({len(only_v18_line)}):")
for field in sorted(only_v18_line):
    field_type = v18_line_stored[field].get('type', 'unknown')
    required = " [REQUERIDO]" if field in v18_line_required else ""
    print(f"  - {field} ({field_type}){required}")

# Guardar análisis en JSON
analysis = {
    'v13_contract': {
        'model': 'contract.contract',
        'total_fields': len(v13_stored_fields),
        'required_fields': v13_required_fields,
        'stored_fields': {k: {'type': v.get('type'), 'required': v.get('required', False)} for k, v in v13_stored_fields.items()}
    },
    'v18_subscription': {
        'model': 'sale.subscription',
        'total_fields': len(v18_stored_fields),
        'required_fields': v18_required_fields,
        'stored_fields': {k: {'type': v.get('type'), 'required': v.get('required', False)} for k, v in v18_stored_fields.items()}
    },
    'v13_line': {
        'model': 'contract.line',
        'total_fields': len(v13_line_stored),
        'required_fields': v13_line_required,
        'stored_fields': {k: {'type': v.get('type'), 'required': v.get('required', False)} for k, v in v13_line_stored.items()}
    },
    'v18_line': {
        'model': 'sale.subscription.line',
        'total_fields': len(v18_line_stored),
        'required_fields': v18_line_required,
        'stored_fields': {k: {'type': v.get('type'), 'required': v.get('required', False)} for k, v in v18_line_stored.items()}
    },
    'comparison': {
        'common_fields': list(common_fields),
        'only_v13': list(only_v13),
        'only_v18': list(only_v18),
        'common_line_fields': list(common_line_fields),
        'only_v13_line': list(only_v13_line),
        'only_v18_line': list(only_v18_line)
    }
}

with open('contract_comparison.json', 'w', encoding='utf-8') as f:
    json.dump(analysis, f, indent=2, ensure_ascii=False, default=str)

print(f"\n✓ Análisis guardado en contract_comparison.json")


