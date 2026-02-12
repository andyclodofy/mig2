# Plan de Migración: contract.contract -> sale.subscription

## Resumen

- **Modelo origen (v13):** `contract.contract` → **Modelo destino (v18):** `sale.subscription`
- **Líneas origen (v13):** `contract.line` → **Líneas destino (v18):** `sale.subscription.line`
- **Total contratos:** 6,468
- **Total líneas:** 8,058

## Correcciones Importantes

### 1. template_id (REQUERIDO en v18)

**✅ CORRECCIÓN:** El `template_id` NO se toma de `contract_template_id` (que no existe en v13), sino que se determina basándose en los campos de recurrencia del contrato:

- `contract_type`: 'sale' (todos los contratos)
- `recurring_rule_type`: 'monthly' (863) o 'yearly' (136)
- `recurring_interval`: 1 (mayoría), 2, 3, o 5
- `recurring_invoicing_type`: 'pre-paid' (todos)

**Acción:**
1. Crear templates en v18 basándose en las combinaciones encontradas:
   - Template Mensual (monthly, interval=1) - 863 contratos
   - Template Anual Intervalo 1 (yearly, interval=1) - 134 contratos
   - Template Anual Intervalo 2 (yearly, interval=2) - 1 contrato
   - Template Anual Intervalo 3 (yearly, interval=3) - 1 contrato
   - Template Anual Intervalo 5 (yearly, interval=5) - 1 contrato

2. Durante la migración, para cada contrato:
   - Extraer `recurring_rule_type` y `recurring_interval`
   - Buscar el template que coincida
   - Asignar `template_id` al subscription

### 2. pricelist_id (REQUERIDO en v18)

**✅ CORRECCIÓN:** El `pricelist_id` se debe **MAPEAR directamente** desde v13, NO usar por defecto.

- 6,004 contratos tienen `pricelist_id` en v13 → **MAPEAR usando pricelist_mapping**
- 464 contratos sin `pricelist_id` → Usar pricelist por defecto de la compañía

**Acción:**
- Exportar `pricelist_id` desde v13
- Mapear usando el mapeo de pricelists migrados
- Si no existe mapeo, usar pricelist por defecto

## Mapeo de Modelos Configurado

Ya agregado en `exceptions/model_name_mapping.json`:
- `contract.contract` → `sale.subscription`
- `contract.line` → `sale.subscription.line`

## Campos a Exportar desde v13

### contract.contract → sale.subscription

**Campos comunes (mapeo directo):**
- `name`, `partner_id`, `company_id`, `date_start`, `code`, `active`
- `fiscal_position_id`, `journal_id`, `pricelist_id`, `user_id`
- `recurring_next_date`, `currency_id`

**Campos para determinar template_id (OBLIGATORIOS):**
- `contract_type` (todos = 'sale')
- `recurring_rule_type` ('monthly' o 'yearly')
- `recurring_interval` (1, 2, 3, 5)
- `recurring_invoicing_type` (todos = 'pre-paid')

**Campos opcionales:**
- `date_end` (puede usarse para determinar estado)
- `is_terminated` (puede usarse para `close_reason_id`)
- `terminate_reason_id` (mapear a `close_reason_id` si existe)

### contract.line → sale.subscription.line

**Campos comunes:**
- `contract_id` → `sale_subscription_id` (mapear después de crear subscriptions)
- `product_id` (usar product_mapping)
- `name` (truncar si es muy largo: v13=text, v18=char)
- `quantity` → `product_uom_qty`
- `price_unit` (o `specific_price` si `price_unit` no existe)
- `discount`, `company_id`

## Campos Requeridos en v18

### sale.subscription
- ✅ `company_id` - Existe en v13
- ✅ `partner_id` - Existe en v13
- ⚠️ `template_id` - **SE DETERMINA** por campos de recurrencia
- ⚠️ `pricelist_id` - **SE MAPEA** desde v13

### sale.subscription.line
- ✅ Ningún campo requerido

## Orden de Migración

1. **Primero:** Crear templates en v18 (ANTES de migrar)
2. **Segundo:** Migrar `sale.subscription` (contracts)
   - Determinar `template_id` por campos de recurrencia
   - Mapear `pricelist_id` desde v13
3. **Tercero:** Migrar `sale.subscription.line` (contract lines)
   - Mapear `sale_subscription_id` usando subscription_mapping

## Configuración en models_to_migrate.txt

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

## Próximos Pasos

1. ✅ Análisis completado
2. ✅ Mapeo de modelos configurado
3. ⏳ Crear templates en v18 (script)
4. ⏳ Modificar migrate.py para:
   - Determinar `template_id` por campos de recurrencia
   - Mapear `pricelist_id` desde v13
   - Mapear `contract_id` → `sale_subscription_id` en líneas
5. ⏳ Agregar a models_to_migrate.txt
6. ⏳ Probar migración con un contrato de prueba
7. ⏳ Ejecutar migración completa
8. ⏳ Verificar resultados


