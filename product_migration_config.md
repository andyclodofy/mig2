# Configuración de Migración de Productos

## Resumen de Modelos

| Modelo | v13 Registros | v18 Registros | Orden | Dependencias |
|--------|---------------|---------------|-------|--------------|
| `product.category` | 13 | 7 | 1 | Ninguna |
| `product.template` | 414 | 357 | 2 | `product.category` |
| `product.product` | 506 | 357 | 3 | `product.template` |
| `product.pricelist` | 58 | 0 | 4 | `res.currency` |
| `product.pricelist.item` | 183 | 0 | 5 | `product.pricelist`, `product.template`, `product.product`, `product.category` |

## Campos Requeridos y Valores por Defecto

### product.category

**Campos requeridos en v13:**
- `name` (char)
- `property_valuation` (selection) - **Ya NO requerido en v18**
- `property_cost_method` (selection) - **Ya NO requerido en v18**

**Campos requeridos en v18:**
- `name` (char)

**Notas:**
- Los campos `property_valuation` y `property_cost_method` ya no son requeridos en v18, pero pueden migrarse como campos opcionales si existen en v13.

### product.template

**Campos requeridos en v13:**
- `name` (char)
- `categ_id` (many2one → `product.category`)
- `uom_id` (many2one → `uom.uom`)
- `uom_po_id` (many2one → `uom.uom`)
- `product_variant_ids` (one2many) - **No se migra directamente**
- `type` (selection)
- `tracking` (selection)
- `sale_line_warn` (selection)

**Nuevos campos requeridos en v18:**
- `service_tracking` (selection) - **Valor por defecto: `'no'`**
- `purchase_line_warn` (selection) - **Valor por defecto: `'no-message'`**
- `ticket_active` (boolean) - **Valor por defecto: `False`**

**Valores de selection:**
- `service_tracking`: `[('no', 'Nothing')]` - Usar `'no'` por defecto
- `purchase_line_warn`: `[('no-message', 'No Message'), ('warning', 'Warning'), ('block', 'Blocking Message')]` - Usar `'no-message'` por defecto
- `sale_line_warn`: `[('no-message', 'No Message'), ('warning', 'Warning'), ('block', 'Blocking Message')]` - Mantener valor de v13

**Campos many2one importantes:**
- `categ_id` → `product.category` (requerido)
- `uom_id` → `uom.uom` (requerido)
- `uom_po_id` → `uom.uom` (requerido)
- `company_id` → `res.company` (opcional)
- `currency_id` → `res.currency` (computed, no migrar)
- `cost_currency_id` → `res.currency` (computed, no migrar)

**Notas:**
- `product_variant_ids` es un campo one2many que se crea automáticamente cuando se crea un `product.product` asociado.
- Los campos `currency_id` y `cost_currency_id` son computed y no deben migrarse.

### product.product

**Campos requeridos en v13:**
- `product_tmpl_id` (many2one → `product.template`) - **Requerido**
- `name` (char)
- `categ_id` (many2one → `product.category`)
- `uom_id` (many2one → `uom.uom`)
- `uom_po_id` (many2one → `uom.uom`)
- `product_variant_ids` (one2many) - **No se migra directamente**
- `type` (selection)
- `tracking` (selection)
- `sale_line_warn` (selection)

**Nuevos campos requeridos en v18:**
- `service_tracking` (selection) - **Valor por defecto: `'no'`**
- `purchase_line_warn` (selection) - **Valor por defecto: `'no-message'`**
- `ticket_active` (boolean) - **Valor por defecto: `False`**

**Valores de selection:**
- `service_tracking`: `[('no', 'Nothing')]` - Usar `'no'` por defecto
- `purchase_line_warn`: `[('no-message', 'No Message'), ('warning', 'Warning'), ('block', 'Blocking Message')]` - Usar `'no-message'` por defecto
- `sale_line_warn`: `[('no-message', 'No Message'), ('warning', 'Warning'), ('block', 'Blocking Message')]` - Mantener valor de v13

**Campos many2one importantes:**
- `product_tmpl_id` → `product.template` (requerido)
- `categ_id` → `product.category` (requerido)
- `uom_id` → `uom.uom` (requerido)
- `uom_po_id` → `uom.uom` (requerido)

**Notas:**
- `product.product` está estrechamente relacionado con `product.template`. En v18, cada `product.template` tiene al menos un `product.product` asociado.
- Los campos `currency_id` y `cost_currency_id` son computed y no deben migrarse.

### product.pricelist

**Campos requeridos en v13 y v18:**
- `name` (char)
- `currency_id` (many2one → `res.currency`)

**Campos many2one importantes:**
- `currency_id` → `res.currency` (requerido)
- `company_id` → `res.company` (opcional)

**Notas:**
- Este modelo no tiene dependencias de productos, pero requiere que `res.currency` esté migrado.
- No hay cambios significativos entre v13 y v18.

### product.pricelist.item

**Campos requeridos en v13:**
- `applied_on` (selection)
- `base` (selection)
- `pricelist_id` (many2one → `product.pricelist`)
- `compute_price` (selection)

**Nuevos campos requeridos en v18:**
- `display_applied_on` (selection) - **Valor por defecto: basado en `applied_on`**

**Valores de selection:**
- `applied_on`: `[('3_global', 'All Products'), ('2_product_category', 'Product Category'), ('1_product', 'Product'), ('0_product_variant', 'Product Variant')]`
- `display_applied_on`: `[('1_product', 'Product'), ('2_product_category', 'Category')]` - **Mapear desde `applied_on`**

**Lógica de mapeo para `display_applied_on`:**
- Si `applied_on == '1_product'` → `display_applied_on = '1_product'`
- Si `applied_on == '2_product_category'` → `display_applied_on = '2_product_category'`
- Si `applied_on == '0_product_variant'` → `display_applied_on = '1_product'` (Product)
- Si `applied_on == '3_global'` → `display_applied_on = '1_product'` (Product) o `'2_product_category'` (Category) - **Revisar lógica**

**Campos many2one importantes:**
- `pricelist_id` → `product.pricelist` (requerido)
- `product_tmpl_id` → `product.template` (opcional, según `applied_on`)
- `product_id` → `product.product` (opcional, según `applied_on`)
- `categ_id` → `product.category` (opcional, según `applied_on`)
- `base_pricelist_id` → `product.pricelist` (opcional)
- `currency_id` → `res.currency` (opcional)
- `company_id` → `res.company` (opcional)

**Notas:**
- `display_applied_on` es un campo nuevo en v18 que debe calcularse basándose en `applied_on`.
- Este modelo depende de `product.pricelist`, `product.template`, `product.product` y `product.category`.

## Orden de Migración

1. **product.category** - Sin dependencias
2. **product.template** - Depende de `product.category`
3. **product.product** - Depende de `product.template`
4. **product.pricelist** - Depende de `res.currency` (debe estar migrado)
5. **product.pricelist.item** - Depende de `product.pricelist`, `product.template`, `product.product`, `product.category`

## Campos a Excluir (Computed sin store)

Los siguientes campos son computed y no deben migrarse:
- `currency_id` (computed)
- `cost_currency_id` (computed)
- `price` (computed)
- `lst_price` (computed)
- `standard_price` (computed en algunos casos)
- `product_variant_ids` (one2many, se crea automáticamente)
- Todos los campos de actividad (`activity_*`)
- Todos los campos de mensajería (`message_*`)

## Campos Many2one a Mapear

Los siguientes campos many2one requieren mapeo de IDs de v13 a v18:
- `categ_id` → `product.category`
- `product_tmpl_id` → `product.template`
- `pricelist_id` → `product.pricelist`
- `uom_id` → `uom.uom` (verificar si existe en v18)
- `uom_po_id` → `uom.uom` (verificar si existe en v18)
- `currency_id` → `res.currency` (si no es computed)
- `company_id` → `res.company` (si existe)

## Valores por Defecto para Campos Nuevos

Cuando se migren registros, se deben agregar los siguientes valores por defecto para campos nuevos requeridos en v18:

### product.template y product.product:
```python
{
    'service_tracking': 'no',
    'purchase_line_warn': 'no-message',
    'ticket_active': False
}
```

### product.pricelist.item:
```python
{
    'display_applied_on': mapear_desde_applied_on(applied_on)
}
```

## Consideraciones Especiales

1. **product.category**: Los campos `property_valuation` y `property_cost_method` ya no son requeridos en v18, pero pueden migrarse como opcionales.

2. **product.template vs product.product**: En v18, la relación entre `product.template` y `product.product` es más estricta. Cada template debe tener al menos un product asociado.

3. **product.pricelist.item.display_applied_on**: Este campo es nuevo y debe calcularse basándose en `applied_on`. La lógica de mapeo debe implementarse en el script de migración.

4. **UoM (Unit of Measure)**: Los campos `uom_id` y `uom_po_id` apuntan a `uom.uom`. Se debe verificar que estos registros existan en v18 o migrarlos primero.

5. **Monedas**: `res.currency` debe estar migrado antes de migrar `product.pricelist`.

