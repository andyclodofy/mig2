# Resumen Ejecutivo: Migración de Contratos

## Situación Actual

### v13 (Origen)
- **contract.contract:** 6,468 registros
- **contract.line:** 8,058 registros
- **Templates:** 0 contratos tienen template asignado (todos sin template)
- **Pricelists:** 6,004 con pricelist, 464 sin pricelist
- **Currency:** Todos tienen currency_id
- **Estado:** 0 terminados, 6,468 activos

### v18 (Destino)
- **sale.subscription:** 0 registros
- **sale.subscription.line:** 0 registros
- **Templates:** 0 templates disponibles ⚠️
- **Pricelists:** 10 pricelists disponibles ✅
- **Stages:** 4 stages disponibles ✅
- **Close reasons:** 5 razones disponibles ✅

## Problemas Críticos Identificados

### 1. template_id Requerido en v18
**Problema:** 
- `template_id` es **REQUERIDO** en `sale.subscription` (v18)
- **0 contratos** en v13 tienen `contract_template_id` asignado
- **0 templates** disponibles en v18

**Solución:**
1. Crear un template por defecto en v18 antes de migrar
2. Asignar este template a todos los subscriptions migrados

### 2. pricelist_id Requerido en v18
**Problema:**
- `pricelist_id` es **REQUERIDO** en `sale.subscription` (v18)
- **464 contratos** en v13 NO tienen `pricelist_id`

**Solución:**
1. Usar el pricelist por defecto de la compañía para contratos sin pricelist
2. O usar el primer pricelist disponible

## Plan de Acción

### Fase 1: Preparación (ANTES de migrar)

1. **Crear template por defecto en v18:**
   ```python
   # Crear sale.subscription.template por defecto
   template_data = {
       'name': 'Template por Defecto (Migración v13)',
       'description': 'Template creado para migración de contratos desde v13'
   }
   default_template_id = v18_conn.create('sale.subscription.template', [template_data])[0]
   ```

2. **Identificar pricelist por defecto:**
   - Usar el pricelist con ID más bajo o el primero disponible
   - O usar el pricelist por defecto de la compañía

### Fase 2: Configuración del Script

1. **Agregar mapeo de modelos:**
   - `contract.contract` -> `sale.subscription`
   - `contract.line` -> `sale.subscription.line`

2. **Agregar a models_to_migrate.txt:**
   ```
   sale.subscription:True
   sale.subscription.line:True
   ```

3. **Configurar campos especiales:**
   - `template_id`: Siempre incluir y asignar template por defecto si no existe
   - `pricelist_id`: Siempre incluir y asignar pricelist por defecto si no existe
   - `currency_id`: Mapear usando currency_mapping

4. **Configurar mapeo de líneas:**
   - `contract_id` -> `sale_subscription_id` (mapear después de crear subscriptions)
   - `quantity` -> `product_uom_qty`
   - `price_unit` -> `price_unit`

### Fase 3: Lógica de Migración

#### Para sale.subscription:

1. **Campos directos:**
   - `name`, `partner_id`, `company_id`, `date_start`, `code`, `active`
   - `fiscal_position_id`, `journal_id`, `user_id`, `recurring_next_date`

2. **Campos con transformación:**
   - `template_id`: 
     - Si `contract_template_id` existe en v13, mapearlo
     - Si no, usar template por defecto
   - `pricelist_id`:
     - Si existe en v13, mapearlo usando pricelist_mapping
     - Si no, usar pricelist por defecto
   - `currency_id`:
     - Si existe en v13, mapearlo usando currency_mapping
     - Si no, usar moneda del pricelist

3. **Campos nuevos en v18:**
   - `stage_id`: Usar stage "In progress" (ID=3) si está activo
   - `in_progress`: `True` si el contrato está activo
   - `to_renew`: `False` por defecto

#### Para sale.subscription.line:

1. **Campos directos:**
   - `product_id`: Mapear usando product_mapping
   - `name`: Truncar si es muy largo (v13=text, v18=char)
   - `discount`: Mapeo directo
   - `company_id`: Mapeo directo

2. **Campos con transformación:**
   - `sale_subscription_id`: Mapear usando subscription_mapping (después de crear subscriptions)
   - `product_uom_qty`: Desde `quantity` de v13
   - `price_unit`: Desde `price_unit` o `specific_price` de v13

3. **Campos calculados (no migrar):**
   - `price_subtotal`, `price_total`: Se calculan automáticamente
   - `currency_id`: Se hereda de la subscription

### Fase 4: Verificación

1. **Cantidad de registros:**
   - `contract.contract` (v13) = `sale.subscription` (v18) ✅
   - `contract.line` (v13) = `sale.subscription.line` (v18) ✅

2. **Integridad:**
   - Todas las líneas tienen `sale_subscription_id` válido
   - Todos los subscriptions tienen `template_id` válido
   - Todos los subscriptions tienen `pricelist_id` válido

## Archivos a Modificar

1. **migrate.py:**
   - Agregar mapeo de modelos (`contract.contract` -> `sale.subscription`)
   - Agregar lógica para `template_id` y `pricelist_id` requeridos
   - Agregar lógica para mapear líneas después de crear subscriptions

2. **models_to_migrate.txt:**
   - Agregar `sale.subscription:True`
   - Agregar `sale.subscription.line:True`

3. **exceptions/field_mappings.json:**
   - Agregar mapeos específicos si es necesario

4. **exceptions/model_name_mapping.json:**
   - Agregar `contract.contract` -> `sale.subscription`
   - Agregar `contract.line` -> `sale.subscription.line`

## Próximos Pasos

1. ✅ Análisis completado
2. ⏳ Crear template por defecto en v18
3. ⏳ Modificar migrate.py para soportar mapeo de modelos diferentes
4. ⏳ Agregar lógica para campos requeridos (template_id, pricelist_id)
5. ⏳ Configurar models_to_migrate.txt
6. ⏳ Probar migración con un contrato de prueba
7. ⏳ Ejecutar migración completa
8. ⏳ Verificar resultados


