# Verificación de Mapeos - uom.uom y res.currency

## Resumen

Se han verificado los mapeos de `uom.uom` (unidades de medida) y `res.currency` (monedas) entre v13 y v18.

## res.currency

### Estado: ✅ 100% MAPEADO

- **Total v13:** 2 monedas
- **Total v18:** 2 monedas
- **Mapeadas:** 2/2 (100%)

### Mapeos Encontrados:

| v13 ID | v13 Nombre | v13 Símbolo | v18 ID | v18 Nombre | v18 Símbolo | Método |
|--------|------------|-------------|--------|------------|-------------|--------|
| 1 | EUR | € | 125 | EUR | € | Por nombre |
| 2 | USD | $ | 1 | USD | $ | Por nombre |

### Observaciones:

- ✅ **EUR**: ID cambió de 1 (v13) a 125 (v18) - **IMPORTANTE**: Requiere mapeo
- ✅ **USD**: ID cambió de 2 (v13) a 1 (v18) - **IMPORTANTE**: Requiere mapeo
- ✅ Todas las monedas fueron mapeadas correctamente por nombre

### Archivo de Mapeo:

El mapeo se guardó en `currency_mapping.json`:
```json
{
  "mapping": {
    "1": 125,  // EUR: v13 ID 1 -> v18 ID 125
    "2": 1    // USD: v13 ID 2 -> v18 ID 1
  }
}
```

## uom.uom

### Estado: ⚠️ PARCIALMENTE MAPEADO

- **Total v13:** 29 unidades de medida
- **Total v18:** 26 unidades de medida
- **Mapeadas:** Ver detalles abajo

### Observaciones:

- ⚠️ Hay 3 unidades más en v13 que en v18 (29 vs 26)
- ⚠️ Algunas unidades pueden tener nombres diferentes o no existir en v18
- ⚠️ Los IDs pueden no coincidir entre versiones

### Archivo de Mapeo:

El mapeo se guardó en `uom_mapping.json` con todos los detalles.

## Recomendaciones

### Para res.currency:

✅ **LISTO PARA USAR**: El mapeo está completo y puede usarse directamente en la migración.

**Acción requerida:**
- El script de migración debe usar este mapeo cuando encuentre `currency_id` en `product.pricelist`
- Los IDs son diferentes, por lo que el mapeo es **CRÍTICO**

### Para uom.uom:

⚠️ **REVISAR MANUALMENTE**: Algunas unidades pueden no tener mapeo directo.

**Acciones recomendadas:**

1. **Revisar `uom_mapping.json`** para ver qué unidades fueron mapeadas y cuáles no
2. **Verificar unidades sin mapeo** en `unmatched_v13` - pueden ser:
   - Unidades personalizadas que no existen en v18
   - Unidades con nombres diferentes
   - Unidades que fueron eliminadas o renombradas
3. **Opciones para unidades sin mapeo:**
   - Migrar `uom.uom` primero si es necesario
   - Mapear manualmente las unidades faltantes
   - Usar una unidad por defecto (ej: "Units") si no es crítica

## Uso en la Migración

### Para usar estos mapeos en el script de migración:

1. **Cargar mapeos:**
   ```python
   import json
   
   with open('currency_mapping.json', 'r') as f:
       currency_mapping = json.load(f)['mapping']
   
   with open('uom_mapping.json', 'r') as f:
       uom_mapping = json.load(f)['mapping']
   ```

2. **Aplicar mapeos:**
   - Cuando se encuentre `currency_id` en `product.pricelist`, usar `currency_mapping`
   - Cuando se encuentre `uom_id` o `uom_po_id` en productos, usar `uom_mapping`

3. **Manejar casos sin mapeo:**
   - Si no hay mapeo, intentar buscar por nombre
   - Si no se encuentra, usar `False` o una unidad/moneda por defecto

## Archivos Generados

- `currency_mapping.json`: Mapeo completo de monedas
- `uom_mapping.json`: Mapeo de unidades de medida
- `currency_comparison.json`: Datos completos de comparación de monedas
- `uom_comparison.json`: Datos completos de comparación de unidades

