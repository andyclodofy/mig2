# Estrategia para Template_ID en Migración de Contratos

## Análisis de Combinaciones en v13

Todos los contratos en v13 tienen estas características:

### Combinación 1: Mensual (863 contratos)
- `contract_type`: 'sale'
- `recurring_rule_type`: 'monthly'
- `recurring_interval`: 1
- `recurring_invoicing_type`: 'pre-paid'

### Combinación 2: Anual (136 contratos)
- `contract_type`: 'sale'
- `recurring_rule_type`: 'yearly'
- `recurring_interval`: 1 (134), 2 (1), 3 (1), 5 (1)
- `recurring_invoicing_type`: 'pre-paid'

## Campos para Crear Templates en v18

### sale.subscription.template campos disponibles:
- `name` (requerido): Nombre del template
- `description`: Descripción
- `recurring_rule_type`: Tipo de recurrencia (monthly, yearly, etc.)
- `recurring_interval`: Intervalo (1, 2, 3, etc.)
- `recurring_rule_boundary`: Límite de regla de recurrencia
- `recurring_invoicing_type`: NO existe en v18 (solo en v13)

## Templates a Crear en v18

### Template 1: Mensual Pre-pago
```python
{
    'name': 'Template Mensual Pre-pago (Migración v13)',
    'description': 'Template para contratos mensuales con pago anticipado migrados desde v13',
    'recurring_rule_type': 'monthly',
    'recurring_interval': 1,
    'recurring_rule_boundary': 'unlimited'  # Verificar valor correcto
}
```

### Template 2: Anual Pre-pago (Intervalo 1)
```python
{
    'name': 'Template Anual Pre-pago Intervalo 1 (Migración v13)',
    'description': 'Template para contratos anuales con pago anticipado migrados desde v13',
    'recurring_rule_type': 'yearly',
    'recurring_interval': 1,
    'recurring_rule_boundary': 'unlimited'
}
```

### Template 3: Anual Pre-pago (Intervalo 2)
```python
{
    'name': 'Template Anual Pre-pago Intervalo 2 (Migración v13)',
    'description': 'Template para contratos anuales cada 2 años migrados desde v13',
    'recurring_rule_type': 'yearly',
    'recurring_interval': 2,
    'recurring_rule_boundary': 'unlimited'
}
```

### Template 4: Anual Pre-pago (Intervalo 3)
```python
{
    'name': 'Template Anual Pre-pago Intervalo 3 (Migración v13)',
    'description': 'Template para contratos anuales cada 3 años migrados desde v13',
    'recurring_rule_type': 'yearly',
    'recurring_interval': 3,
    'recurring_rule_boundary': 'unlimited'
}
```

### Template 5: Anual Pre-pago (Intervalo 5)
```python
{
    'name': 'Template Anual Pre-pago Intervalo 5 (Migración v13)',
    'description': 'Template para contratos anuales cada 5 años migrados desde v13',
    'recurring_rule_type': 'yearly',
    'recurring_interval': 5,
    'recurring_rule_boundary': 'unlimited'
}
```

## Lógica de Asignación de Template_ID

Durante la migración, para cada contrato:

1. **Extraer campos de recurrencia del contrato v13:**
   - `recurring_rule_type` (monthly/yearly)
   - `recurring_interval` (1, 2, 3, 5)

2. **Buscar template correspondiente en v18:**
   ```python
   template_domain = [
       ['recurring_rule_type', '=', recurring_rule_type],
       ['recurring_interval', '=', recurring_interval]
   ]
   templates = v18_conn.search_read('sale.subscription.template', template_domain, ['id'])
   if templates:
       template_id = templates[0]['id']
   else:
       # Usar template mensual por defecto si no se encuentra
       template_id = default_monthly_template_id
   ```

3. **Asignar template_id al subscription en v18**

## Implementación

1. **Antes de migrar:** Crear los 5 templates en v18
2. **Durante la migración:** Para cada contrato, buscar el template que coincida con sus campos de recurrencia
3. **Si no se encuentra:** Usar el template mensual (intervalo 1) como fallback


