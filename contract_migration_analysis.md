# Análisis de Migración: contract.contract (v13) -> sale.subscription (v18)

## Resumen Ejecutivo

- **Modelo origen (v13):** `contract.contract` (6,468 registros)
- **Modelo destino (v18):** `sale.subscription` (0 registros actualmente)
- **Líneas origen (v13):** `contract.line` (8,058 registros)
- **Líneas destino (v18):** `sale.subscription.line` (0 registros actualmente)

## Campos Requeridos en v18

### sale.subscription (v18) - Campos Requeridos:
1. **`company_id`** ✅ - Existe en v13, se puede mapear directamente
2. **`partner_id`** ✅ - Existe en v13, se puede mapear directamente
3. **`template_id`** ⚠️ - **REQUERIDO**: Requerido en v18, se determina basándose en:
   - `contract_type`: 'sale' (todos los contratos)
   - `recurring_rule_type`: 'monthly' (863 contratos) o 'yearly' (136 contratos)
   - `recurring_interval`: 1, 2, 3 o 5 (mayoría es 1)
   - `recurring_invoicing_type`: 'pre-paid' (todos)
   - **SOLUCIÓN**: Crear templates en v18 basándose en estas combinaciones, luego buscar/seleccionar el template que coincida con los campos del contrato
4. **`pricelist_id`** ⚠️ - **REQUERIDO**: Requerido en v18:
   - Existe en v13 y **DEBE MAPEARSE** directamente desde v13
   - 6,004 contratos tienen pricelist, 464 sin pricelist
   - **SOLUCIÓN**: Mapear `pricelist_id` desde v13 usando el mapeo de pricelists. Si no existe, usar pricelist por defecto de la compañía

### sale.subscription.line (v18) - Campos Requeridos:
- **Ninguno** ✅ - No hay campos requeridos en v18

## Mapeo de Campos Principales

### Campos Comunes (Mapeo Directo)

| Campo v13 (contract.contract) | Campo v18 (sale.subscription) | Tipo | Notas |
|-------------------------------|-------------------------------|------|-------|
| `id` | `id` | integer | Se mapea vía migration.tracking |
| `name` | `name` | char | ✅ Mapeo directo |
| `partner_id` | `partner_id` | many2one | ✅ Mapeo directo (requerido en ambos) |
| `company_id` | `company_id` | many2one | ✅ Mapeo directo (requerido en ambos) |
| `date_start` | `date_start` | date | ✅ Mapeo directo |
| `code` | `code` | char | ✅ Mapeo directo |
| `active` | `active` | boolean | ✅ Mapeo directo |
| `fiscal_position_id` | `fiscal_position_id` | many2one | ✅ Mapeo directo |
| `journal_id` | `journal_id` | many2one | ✅ Mapeo directo |
| `pricelist_id` | `pricelist_id` | many2one | ⚠️ Requerido en v18, puede faltar en v13 |
| `user_id` | `user_id` | many2one | ✅ Mapeo directo |
| `recurring_next_date` | `recurring_next_date` | date | ✅ Mapeo directo |

### Campos que Necesitan Transformación

| Campo v13 | Campo v18 | Transformación |
|----------|-----------|----------------|
| `contract_template_id` | `template_id` | ⚠️ Requerido en v18, usar template por defecto si no existe |
| `date_end` | - | ❌ No existe en v18 (se puede usar `close_reason_id` si está terminado) |
| `currency_id` | `currency_id` | ✅ Mapeo directo (usar currency_mapping) |
| `manual_currency_id` | `currency_id` | Si `currency_id` no existe, usar `manual_currency_id` |

### Campos Solo en v13 (No se Migran)

- `contract_type` - No existe en v18
- `recurring_rule_type` - No existe en v18
- `recurring_interval` - No existe en v18
- `recurring_invoicing_type` - No existe en v18
- `date_end` - No existe en v18
- `is_terminated` - Usar `close_reason_id` en v18
- `terminate_date` - Usar `close_reason_id` en v18
- `terminate_reason_id` - Mapear a `close_reason_id` en v18
- `contract_line_ids` - Se migra como `sale_subscription_line_ids` (one2many)

### Campos Solo en v18 (Valores por Defecto)

| Campo v18 | Tipo | Valor por Defecto | Notas |
|-----------|------|-------------------|-------|
| `template_id` | many2one | **REQUERIDO** | Crear template por defecto o usar existente |
| `pricelist_id` | many2one | **REQUERIDO** | Usar pricelist por defecto si no existe en v13 |
| `currency_id` | many2one | Moneda del pricelist | Si no existe, usar del pricelist |
| `description` | text | `""` | Vacío si no hay equivalente |
| `terms` | text | `""` | Vacío si no hay equivalente |
| `stage_id` | many2one | Stage por defecto | Buscar stage inicial |
| `in_progress` | boolean | `True` | Si el contrato está activo |
| `to_renew` | boolean | `False` | Valor por defecto |

## Mapeo de Líneas

### Campos Comunes en Líneas

| Campo v13 (contract.line) | Campo v18 (sale.subscription.line) | Tipo | Notas |
|---------------------------|-----------------------------------|------|-------|
| `contract_id` | `sale_subscription_id` | many2one | ⚠️ Nombre diferente, mapear después de crear subscription |
| `product_id` | `product_id` | many2one | ✅ Mapeo directo |
| `name` | `name` | text/char | ⚠️ v13=text, v18=char (truncar si es necesario) |
| `discount` | `discount` | float | ✅ Mapeo directo |
| `company_id` | `company_id` | many2one | ✅ Mapeo directo |

### Campos que Necesitan Transformación

| Campo v13 | Campo v18 | Transformación |
|----------|-----------|----------------|
| `quantity` | `product_uom_qty` | ✅ Mapeo directo (nombre diferente) |
| `price_unit` | `price_unit` | ✅ Mapeo directo |
| `specific_price` | `price_unit` | Si `price_unit` no existe, usar `specific_price` |
| `uom_id` | - | ❌ No existe en v18 (se usa UoM del producto) |

### Campos Solo en v13 (No se Migran)

- `date_start` - No existe en v18
- `date_end` - No existe en v18
- `recurring_rule_type` - No existe en v18
- `recurring_interval` - No existe en v18
- `recurring_invoicing_type` - No existe en v18
- `recurring_next_date` - No existe en v18
- `uom_id` - No existe en v18 (se usa del producto)
- `is_canceled` - No existe en v18
- `is_auto_renew` - No existe en v18

### Campos Solo en v18 (Valores por Defecto)

| Campo v18 | Tipo | Valor por Defecto | Notas |
|-----------|------|-------------------|-------|
| `currency_id` | many2one | Moneda de la subscription | Heredar de subscription |
| `price_subtotal` | monetary | Calculado | Se calcula automáticamente |
| `price_total` | monetary | Calculado | Se calcula automáticamente |
| `tax_ids` | many2many | Vacío | Se puede mapear desde v13 si existe |

## Estrategia de Migración

### 1. Preparación

1. **Crear template por defecto en v18:**
   - Si no existe ningún template, crear uno por defecto
   - O usar el template existente si hay uno

2. **Verificar pricelists:**
   - Asegurar que todos los contratos tengan `pricelist_id` en v13
   - Si no, usar pricelist por defecto

3. **Mapear monedas:**
   - Usar `currency_mapping.json` existente
   - Si `currency_id` no existe, usar `manual_currency_id`
   - Si ninguno existe, usar moneda del pricelist

### 2. Orden de Migración

1. **Primero:** Migrar `sale.subscription` (contracts)
   - Mapear campos comunes
   - Asignar `template_id` (requerido)
   - Asignar `pricelist_id` (requerido)
   - Mapear `currency_id`

2. **Segundo:** Migrar `sale.subscription.line` (contract lines)
   - Mapear `sale_subscription_id` usando el mapeo de subscriptions
   - Mapear campos comunes
   - Mapear `product_id` usando el mapeo de productos
   - Asignar `product_uom_qty` desde `quantity`

### 3. Configuración en models_to_migrate.txt

```
# ============================================
# MODELOS DE SUSCRIPCIONES (CONTRATOS)
# ============================================
# PREREQUISITOS: res.partner, product.pricelist, res.currency deben estar migrados
# Orden de migración:
# 1. Suscripciones (depende de: res.partner, product.pricelist, sale.subscription.template)
# 2. Líneas de suscripción (depende de: sale.subscription, product.product)

sale.subscription:True
sale.subscription.line:True
```

### 4. Mapeo de Modelos

Necesitamos agregar al `model_name_mapping`:
- `contract.contract` -> `sale.subscription`
- `contract.line` -> `sale.subscription.line`

### 5. Campos Especiales a Incluir

En `get_stored_fields`, incluir siempre:
- `template_id` para `sale.subscription` (requerido)
- `pricelist_id` para `sale.subscription` (requerido)
- `currency_id` para `sale.subscription` (si existe en v13)
- `contract_template_id` para `contract.contract` (para mapear a template_id)

## Problemas Identificados y Soluciones

### Problema 1: template_id Requerido
**Solución:**
- Si `contract_template_id` existe en v13, mapearlo a `template_id` en v18
- Si no existe, crear o usar un template por defecto
- Verificar si existe `sale.subscription.template` en v18, si no, crear uno

### Problema 2: pricelist_id Requerido
**Solución:**
- Si `pricelist_id` existe en v13, mapearlo usando el mapeo de pricelists
- Si no existe, usar el pricelist por defecto de la compañía

### Problema 3: currency_id
**Solución:**
- Prioridad 1: `currency_id` de v13 (si existe)
- Prioridad 2: `manual_currency_id` de v13 (si existe)
- Prioridad 3: Moneda del `pricelist_id` mapeado
- Prioridad 4: Moneda por defecto (EUR)

### Problema 4: Líneas sin UoM
**Solución:**
- En v18, `uom_id` no existe en las líneas
- Se usa el UoM del producto automáticamente
- No necesitamos mapear `uom_id` de v13

## Verificaciones Post-Migración

1. **Cantidad de registros:**
   - `contract.contract` (v13) = `sale.subscription` (v18) ✅
   - `contract.line` (v13) = `sale.subscription.line` (v18) ✅

2. **Integridad referencial:**
   - Todas las líneas tienen `sale_subscription_id` válido
   - Todos los subscriptions tienen `template_id` válido
   - Todos los subscriptions tienen `pricelist_id` válido

3. **Campos requeridos:**
   - Todos los subscriptions tienen `partner_id`, `company_id`, `template_id`, `pricelist_id`

