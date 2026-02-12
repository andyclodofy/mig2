#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para investigar la estructura de modelos de productos en v13 y v18
"""

import sys
sys.path.insert(0, '.')
from migrate import OdooConnection
import os
from dotenv import load_dotenv
import json
from datetime import datetime

load_dotenv()

# Conectar a v13
v13_conn = OdooConnection(
    os.getenv('V13_URL', 'http://localhost:8069'),
    os.getenv('V13_DB', 'odoo13'),
    os.getenv('V13_USERNAME', 'admin'),
    os.getenv('V13_PASSWORD', 'admin')
)

# Conectar a v18
v18_conn = OdooConnection(
    os.getenv('V18_URL', 'http://localhost:8069'),
    os.getenv('V18_DB', 'odoo18'),
    os.getenv('V18_USERNAME', 'admin'),
    os.getenv('V18_PASSWORD', 'admin')
)

models = [
    'product.template',
    'product.product',
    'product.category',
    'product.pricelist',
    'product.pricelist.item'
]

output_dir = 'product_investigation'
os.makedirs(output_dir, exist_ok=True)

for model in models:
    print(f'\n{"="*80}')
    print(f'INVESTIGANDO: {model}')
    print(f'{"="*80}')
    
    # Contar registros
    v13_count = v13_conn.count_records(model)
    v18_count = v18_conn.count_records(model)
    print(f'v13: {v13_count} registros')
    print(f'v18: {v18_count} registros')
    
    # Obtener campos
    v13_fields = v13_conn.get_fields(model)
    v18_fields = v18_conn.get_fields(model)
    
    # Campos requeridos
    v13_required = {f: info for f, info in v13_fields.items() if info.get('required', False)}
    v18_required = {f: info for f, info in v18_fields.items() if info.get('required', False)}
    
    print(f'\nv13 campos requeridos ({len(v13_required)}):')
    for field, info in v13_required.items():
        print(f'  - {field}: {info.get("type")} - {info.get("string", "")}')
    
    print(f'\nv18 campos requeridos ({len(v18_required)}):')
    for field, info in v18_required.items():
        print(f'  - {field}: {info.get("type")} - {info.get("string", "")}')
    
    # Diferencias
    new_required = set(v18_required.keys()) - set(v13_required.keys())
    removed_required = set(v13_required.keys()) - set(v18_required.keys())
    
    if new_required:
        print(f'\n⚠️  NUEVOS campos requeridos en v18: {new_required}')
        for field in new_required:
            info = v18_required[field]
            print(f'  - {field}: {info.get("type")} - {info.get("string", "")} - Default: {info.get("default", "N/A")}')
    
    if removed_required:
        print(f'\n✅ Ya NO requeridos en v18: {removed_required}')
    
    # Campos many2one
    v13_m2o = {f: info for f, info in v13_fields.items() if info.get('type') == 'many2one'}
    v18_m2o = {f: info for f, info in v18_fields.items() if info.get('type') == 'many2one'}
    
    print(f'\nv13 campos many2one ({len(v13_m2o)}): {list(v13_m2o.keys())[:10]}...')
    print(f'v18 campos many2one ({len(v18_m2o)}): {list(v18_m2o.keys())[:10]}...')
    
    # Campos computed sin store
    v13_computed = {f: info for f, info in v13_fields.items() if not info.get('store', True)}
    v18_computed = {f: info for f, info in v18_fields.items() if not info.get('store', True)}
    
    print(f'\nv13 campos computed sin store ({len(v13_computed)}): {list(v13_computed.keys())[:10]}...')
    print(f'v18 campos computed sin store ({len(v18_computed)}): {list(v18_computed.keys())[:10]}...')
    
    # Obtener un registro de ejemplo de v13
    if v13_count > 0:
        print(f'\n📋 Obteniendo registro de ejemplo de v13...')
        try:
            # Filtrar campos que pueden causar problemas de permisos
            safe_fields = [f for f in list(v13_fields.keys())[:50] 
                          if not any(x in f.lower() for x in ['valuation', 'stock_move', 'stock_quant'])]
            
            example = v13_conn.search_read(
                model,
                [],
                safe_fields,
                limit=1
            )
            
            if example:
                example_file = os.path.join(output_dir, f'{model.replace(".", "_")}_v13_example.json')
                with open(example_file, 'w', encoding='utf-8') as f:
                    json.dump(example[0], f, indent=2, ensure_ascii=False, default=str)
                print(f'  ✓ Guardado en: {example_file}')
                
                # Mostrar campos importantes
                important_fields = ['id', 'name', 'active', 'create_date', 'write_date']
                important_fields.extend([f for f in v13_required.keys() if f not in important_fields])
                
                print(f'\n  Campos importantes del ejemplo:')
                for field in important_fields[:15]:
                    if field in example[0]:
                        value = example[0][field]
                        if isinstance(value, (list, tuple)) and len(value) > 0:
                            print(f'    {field}: [{value[0]}, "{value[1] if len(value) > 1 else ""}"]')
                        else:
                            print(f'    {field}: {value}')
        except Exception as e:
            print(f'  ⚠️  Error obteniendo ejemplo de v13: {e}')
    
    # Obtener un registro de ejemplo de v18
    if v18_count > 0:
        print(f'\n📋 Obteniendo registro de ejemplo de v18...')
        try:
            # Filtrar campos que pueden causar problemas de permisos
            safe_fields = [f for f in list(v18_fields.keys())[:50] 
                          if not any(x in f.lower() for x in ['valuation', 'stock_move', 'stock_quant'])]
            
            example = v18_conn.search_read(
                model,
                [],
                safe_fields,
                limit=1
            )
            
            if example:
                example_file = os.path.join(output_dir, f'{model.replace(".", "_")}_v18_example.json')
                with open(example_file, 'w', encoding='utf-8') as f:
                    json.dump(example[0], f, indent=2, ensure_ascii=False, default=str)
                print(f'  ✓ Guardado en: {example_file}')
        except Exception as e:
            print(f'  ⚠️  Error obteniendo ejemplo de v18: {e}')
    
    # Guardar análisis completo
    analysis = {
        'model': model,
        'v13_count': v13_count,
        'v18_count': v18_count,
        'v13_required_fields': {f: {'type': info.get('type'), 'string': info.get('string'), 'default': info.get('default')} 
                               for f, info in v13_required.items()},
        'v18_required_fields': {f: {'type': info.get('type'), 'string': info.get('string'), 'default': info.get('default')} 
                               for f, info in v18_required.items()},
        'new_required_in_v18': list(new_required),
        'removed_required_in_v18': list(removed_required),
        'v13_many2one_fields': {f: {'relation': info.get('relation'), 'string': info.get('string')} 
                               for f, info in v13_m2o.items()},
        'v18_many2one_fields': {f: {'relation': info.get('relation'), 'string': info.get('string')} 
                               for f, info in v18_m2o.items()},
        'v13_computed_fields': list(v13_computed.keys()),
        'v18_computed_fields': list(v18_computed.keys()),
    }
    
    analysis_file = os.path.join(output_dir, f'{model.replace(".", "_")}_analysis.json')
    with open(analysis_file, 'w', encoding='utf-8') as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False, default=str)
    print(f'\n  ✓ Análisis completo guardado en: {analysis_file}')

print(f'\n{"="*80}')
print('INVESTIGACIÓN COMPLETADA')
print(f'{"="*80}')
print(f'Archivos guardados en: {output_dir}/')

