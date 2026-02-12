#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para crear templates de suscripción en v18 basándose en las combinaciones
de recurrencia encontradas en los contratos de v13.
"""

import os
from dotenv import load_dotenv
load_dotenv()

from migrate import OdooConnection

v18_url = os.getenv('V18_URL', 'http://localhost:8069')
v18_db = os.getenv('V18_DB', '105')
v18_username = os.getenv('V18_USERNAME', 'admin')
v18_password = os.getenv('V18_PASSWORD', 'admin')

v18_conn = OdooConnection(v18_url, v18_db, v18_username, v18_password)

# Templates a crear basados en las combinaciones encontradas
templates_to_create = [
    {
        'name': 'Template Mensual Pre-pago (Migración v13)',
        'description': 'Template para contratos mensuales con pago anticipado migrados desde v13',
        'recurring_rule_type': 'monthly',
        'recurring_interval': 1,
        'recurring_rule_boundary': False,  # boolean en v18
        'recurring_rule_count': 0,  # 0 = ilimitado
        'code': 'TEMPLATE_MONTHLY_V13'
    },
    {
        'name': 'Template Anual Pre-pago Intervalo 1 (Migración v13)',
        'description': 'Template para contratos anuales con pago anticipado migrados desde v13',
        'recurring_rule_type': 'yearly',
        'recurring_interval': 1,
        'recurring_rule_boundary': False,
        'recurring_rule_count': 0,
        'code': 'TEMPLATE_YEARLY_1_V13'
    },
    {
        'name': 'Template Anual Pre-pago Intervalo 2 (Migración v13)',
        'description': 'Template para contratos anuales cada 2 años migrados desde v13',
        'recurring_rule_type': 'yearly',
        'recurring_interval': 2,
        'recurring_rule_boundary': False,
        'recurring_rule_count': 0,
        'code': 'TEMPLATE_YEARLY_2_V13'
    },
    {
        'name': 'Template Anual Pre-pago Intervalo 3 (Migración v13)',
        'description': 'Template para contratos anuales cada 3 años migrados desde v13',
        'recurring_rule_type': 'yearly',
        'recurring_interval': 3,
        'recurring_rule_boundary': False,
        'recurring_rule_count': 0,
        'code': 'TEMPLATE_YEARLY_3_V13'
    },
    {
        'name': 'Template Anual Pre-pago Intervalo 5 (Migración v13)',
        'description': 'Template para contratos anuales cada 5 años migrados desde v13',
        'recurring_rule_type': 'yearly',
        'recurring_interval': 5,
        'recurring_rule_boundary': False,
        'recurring_rule_count': 0,
        'code': 'TEMPLATE_YEARLY_5_V13'
    }
]

print("=" * 80)
print("CREACIÓN DE TEMPLATES DE SUSCRIPCIÓN EN V18")
print("=" * 80)

# Verificar si ya existen templates
existing_templates = v18_conn.search_read('sale.subscription.template', [], ['id', 'name', 'code', 'recurring_rule_type', 'recurring_interval'])

print(f"\nTemplates existentes en v18: {len(existing_templates)}")
for t in existing_templates:
    print(f"  - ID={t['id']}: {t['name']} (code: {t.get('code', 'N/A')})")

# Crear templates
created_templates = {}
for template_data in templates_to_create:
    code = template_data['code']
    
    # Verificar si ya existe un template con este código
    existing = v18_conn.search_read('sale.subscription.template', [['code', '=', code]], ['id', 'name'])
    
    if existing:
        print(f"\n✓ Template '{template_data['name']}' ya existe (ID={existing[0]['id']})")
        created_templates[code] = existing[0]['id']
    else:
        try:
            # Verificar valores válidos para recurring_rule_type
            # Intentar crear el template
            template_id = v18_conn.create('sale.subscription.template', [template_data])
            if template_id and len(template_id) > 0:
                print(f"\n✓ Template '{template_data['name']}' creado (ID={template_id[0]})")
                created_templates[code] = template_id[0]
            else:
                print(f"\n✗ Error creando template '{template_data['name']}': No se retornó ID")
        except Exception as e:
            print(f"\n✗ Error creando template '{template_data['name']}': {e}")
            # Intentar crear sin recurring_rule_type si ese es el problema
            try:
                template_data_fallback = template_data.copy()
                # Verificar qué campos son requeridos
                fields_info = v18_conn.get_fields('sale.subscription.template')
                required_fields = [f for f, info in fields_info.items() if info.get('required', False) and f != 'name']
                print(f"  Campos requeridos: {required_fields}")
                
                # Intentar crear solo con campos requeridos y básicos
                minimal_template = {
                    'name': template_data['name'],
                    'description': template_data.get('description', ''),
                }
                if 'code' in fields_info:
                    minimal_template['code'] = template_data.get('code', '')
                
                template_id = v18_conn.create('sale.subscription.template', [minimal_template])
                if template_id and len(template_id) > 0:
                    print(f"  ✓ Template creado con campos mínimos (ID={template_id[0]})")
                    # Intentar actualizar con los campos adicionales
                    try:
                        v18_conn.update('sale.subscription.template', template_id[0], {
                            'recurring_rule_type': template_data.get('recurring_rule_type'),
                            'recurring_interval': template_data.get('recurring_interval'),
                            'recurring_rule_boundary': template_data.get('recurring_rule_boundary', False),
                            'recurring_rule_count': template_data.get('recurring_rule_count', 0)
                        })
                        print(f"  ✓ Template actualizado con campos de recurrencia")
                    except Exception as e2:
                        print(f"  ⚠ No se pudieron actualizar campos de recurrencia: {e2}")
                    created_templates[code] = template_id[0]
            except Exception as e2:
                print(f"  ✗ Error en fallback: {e2}")

# Guardar mapeo de templates
if created_templates:
    import json
    template_mapping = {}
    
    # Obtener todos los templates con sus características
    all_templates = v18_conn.search_read('sale.subscription.template', [], 
        ['id', 'name', 'code', 'recurring_rule_type', 'recurring_interval', 'recurring_rule_boundary', 'recurring_rule_count'])
    
    for t in all_templates:
        key = f"{t.get('recurring_rule_type', 'unknown')}_{t.get('recurring_interval', 0)}"
        template_mapping[key] = {
            'template_id': t['id'],
            'name': t['name'],
            'code': t.get('code', ''),
            'recurring_rule_type': t.get('recurring_rule_type'),
            'recurring_interval': t.get('recurring_interval'),
            'recurring_rule_boundary': t.get('recurring_rule_boundary', False),
            'recurring_rule_count': t.get('recurring_rule_count', 0)
        }
    
    with open('subscription_template_mapping.json', 'w', encoding='utf-8') as f:
        json.dump(template_mapping, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"\n✓ Mapeo de templates guardado en subscription_template_mapping.json")

print("\n" + "=" * 80)
print("RESUMEN:")
print("=" * 80)
print(f"Templates creados/encontrados: {len(created_templates)}")
for code, template_id in created_templates.items():
    print(f"  - {code}: ID={template_id}")


