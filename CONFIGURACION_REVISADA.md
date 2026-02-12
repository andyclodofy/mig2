# Revisión de Configuración - Migración de Productos

## ✅ Estado de la Configuración

### 1. Archivo `models_to_migrate.txt`
**Estado: ✓ CORRECTO**

- Orden de migración correcto:
  1. `product.category` (sin dependencias)
  2. `product.template` (depende de `product.category`)
  3. `product.product` (depende de `product.template`)
  4. `product.pricelist` (depende de `res.currency`)
  5. `product.pricelist.item` (depende de todos los anteriores)

- Todos los modelos tienen `allow_many2one=True` ✓

### 2. Lógica de Valores por Defecto en `migrate.py`
**Estado: ✓ IMPLEMENTADO CORRECTAMENTE**

#### Para `product.template` y `product.product`:
- ✓ `service_tracking = 'no'` (agregado automáticamente si no existe)
- ✓ `purchase_line_warn = 'no-message'` (agregado automáticamente si no existe)
- ✓ `ticket_active = False` (agregado automáticamente si no existe)

**Ubicación en código:** Líneas 2301-2311

#### Para `product.pricelist.item`:
- ✓ `display_applied_on` (calculado desde `applied_on`):
  - `applied_on = '1_product'` → `display_applied_on = '1_product'`
  - `applied_on = '2_product_category'` → `display_applied_on = '2_product_category'`
  - `applied_on = '0_product_variant'` → `display_applied_on = '1_product'`
  - `applied_on = '3_global'` → `display_applied_on = '1_product'`
  - Valor por defecto: `'1_product'`

**Ubicación en código:** Líneas 2313-2329

### 3. Archivo `exceptions/field_mappings.json`
**Estado: ✓ CONFIGURADO**

- ✓ Mapeos agregados para `product.template`
- ✓ Mapeos agregados para `product.product`
- ✓ Mapeos agregados para `product.pricelist.item`

### 4. Documentación
**Estado: ✓ COMPLETA**

- ✓ `product_migration_config.md` creado con toda la información
- ✓ Análisis detallados en `product_investigation/`

## ⚠️ Advertencias y Consideraciones

### 1. Dependencias Externas

#### `res.currency` (requerido para `product.pricelist`)
- **Estado:** ✓ 2 monedas existentes en v18
- **Mapeo:** ⚠️ Sin mapeos de migración (0 registros mapeados)
- **Acción:** Si las monedas en v18 tienen IDs diferentes a v13, puede ser necesario:
  - Migrar `res.currency` primero, O
  - Mapear manualmente los IDs de monedas en `product.pricelist`

#### `uom.uom` (requerido para `product.template` y `product.product`)
- **Estado:** ✓ 26 unidades de medida existentes en v18
- **Mapeo:** ⚠️ Sin mapeos de migración (0 registros mapeados)
- **Acción:** Si las unidades de medida en v18 tienen IDs diferentes a v13, puede ser necesario:
  - Migrar `uom.uom` primero, O
  - Mapear manualmente los IDs de unidades de medida

#### `res.company` (opcional para varios modelos)
- **Estado:** ⚠️ Sin mapeos de migración
- **Acción:** Si `company_id` es requerido y no está mapeado, el script intentará usar la compañía por defecto de v18

### 2. Campos Computed (No se Migran)
Los siguientes campos son computed y NO se migrarán automáticamente:
- `currency_id` (computed en product.template/product.product)
- `cost_currency_id` (computed)
- `price` (computed)
- `lst_price` (computed)
- `standard_price` (computed en algunos casos)
- `product_variant_ids` (one2many, se crea automáticamente)

### 3. Campos Many2one que Requieren Mapeo

Los siguientes campos many2one necesitarán mapeo de IDs v13 → v18:

#### `product.category`:
- `parent_id` → `product.category` (si existe)

#### `product.template`:
- `categ_id` → `product.category` (requerido)
- `uom_id` → `uom.uom` (requerido) ⚠️ Verificar mapeo
- `uom_po_id` → `uom.uom` (requerido) ⚠️ Verificar mapeo
- `company_id` → `res.company` (opcional) ⚠️ Verificar mapeo

#### `product.product`:
- `product_tmpl_id` → `product.template` (requerido)
- `categ_id` → `product.category` (requerido)
- `uom_id` → `uom.uom` (requerido) ⚠️ Verificar mapeo
- `uom_po_id` → `uom.uom` (requerido) ⚠️ Verificar mapeo

#### `product.pricelist`:
- `currency_id` → `res.currency` (requerido) ⚠️ Verificar mapeo
- `company_id` → `res.company` (opcional) ⚠️ Verificar mapeo

#### `product.pricelist.item`:
- `pricelist_id` → `product.pricelist` (requerido)
- `product_tmpl_id` → `product.template` (opcional, según `applied_on`)
- `product_id` → `product.product` (opcional, según `applied_on`)
- `categ_id` → `product.category` (opcional, según `applied_on`)
- `base_pricelist_id` → `product.pricelist` (opcional)
- `currency_id` → `res.currency` (opcional) ⚠️ Verificar mapeo
- `company_id` → `res.company` (opcional) ⚠️ Verificar mapeo

## 📋 Checklist Pre-Migración

Antes de ejecutar la migración, verificar:

- [ ] **Dependencias básicas migradas:**
  - [ ] `res.partner` ✓ (ya migrado según `models_to_migrate.txt`)
  - [ ] `res.users` ✓ (ya migrado según `models_to_migrate.txt`)

- [ ] **Dependencias de productos:**
  - [ ] `res.currency` - Verificar si necesita migración o mapeo manual
  - [ ] `uom.uom` - Verificar si necesita migración o mapeo manual
  - [ ] `res.company` - Verificar si necesita migración o mapeo manual

- [ ] **Configuración verificada:**
  - [x] `models_to_migrate.txt` con orden correcto
  - [x] Valores por defecto implementados en `migrate.py`
  - [x] `field_mappings.json` actualizado
  - [x] Documentación completa

- [ ] **Pruebas recomendadas:**
  - [ ] Probar migración de `product.category` primero (sin dependencias)
  - [ ] Verificar que los mapeos de `categ_id` funcionen correctamente
  - [ ] Probar migración de `product.template` con un registro de prueba
  - [ ] Verificar que los campos nuevos requeridos se agreguen correctamente

## 🚀 Próximos Pasos

1. **Verificar mapeos de dependencias:**
   ```bash
   # Verificar si uom.uom necesita migración
   # Verificar si res.currency necesita migración
   ```

2. **Ejecutar migración en orden:**
   - Primero: `product.category`
   - Segundo: `product.template`
   - Tercero: `product.product`
   - Cuarto: `product.pricelist` (si res.currency está mapeado)
   - Quinto: `product.pricelist.item`

3. **Monitorear logs:**
   - Revisar `logs/migration_*.log` para ver progreso
   - Revisar `logs/errors_*.log` para ver errores
   - Revisar `logs/debug_*.log` para detalles

## 📝 Notas Adicionales

1. **product.category**: Los campos `property_valuation` y `property_cost_method` ya no son requeridos en v18, pero se migrarán como opcionales si existen en v13.

2. **product.template vs product.product**: En v18, cada `product.template` debe tener al menos un `product.product` asociado. El script manejará esto automáticamente.

3. **product.pricelist.item.display_applied_on**: Este campo es nuevo en v18 y se calcula automáticamente desde `applied_on` según la lógica implementada.

4. **Campos many2one sin mapeo**: Si un campo many2one no tiene mapeo (ej: `uom_id`, `currency_id`), el script intentará:
   - Buscar por nombre si está disponible
   - Usar `False` si no se encuentra (puede causar errores si el campo es requerido)

## ✅ Conclusión

La configuración está **COMPLETA y LISTA** para la migración. Los únicos puntos de atención son:

1. **Verificar mapeos de `uom.uom` y `res.currency`** antes de migrar productos que los requieren
2. **Probar primero con `product.category`** (sin dependencias) para validar el flujo
3. **Monitorear los logs** durante la migración para detectar problemas de mapeo

