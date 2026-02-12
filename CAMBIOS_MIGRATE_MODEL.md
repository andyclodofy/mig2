# Cambios en MIGRATE_MODEL - Soporte para Múltiples Modelos

## ✅ Cambio Implementado

La variable de entorno `MIGRATE_MODEL` ahora soporta múltiples modelos separados por comas.

## 📝 Uso

### Antes (solo un modelo):
```bash
export MIGRATE_MODEL=product.category
python3 migrate.py
```

### Ahora (múltiples modelos):
```bash
export MIGRATE_MODEL=product.category,product.template,product.product
python3 migrate.py
```

### Ejemplos:

```bash
# Un solo modelo
export MIGRATE_MODEL=product.category

# Múltiples modelos (sin espacios)
export MIGRATE_MODEL=product.category,product.template,product.product

# Múltiples modelos (con espacios - se limpian automáticamente)
export MIGRATE_MODEL="product.category, product.template , product.product"
```

## 🔧 Funcionamiento

1. **Parsing:** El script divide la variable por comas y limpia espacios en blanco
2. **Configuración:** Para cada modelo, busca `allow_many2one` en `models_to_migrate.txt`
3. **Migración:** Migra los modelos en el orden especificado (respetando dependencias si están en la lista)

## 📋 Ejemplo Completo

```bash
# Migrar solo las categorías de productos
export MIGRATE_MODEL=product.category
python3 migrate.py

# Migrar categorías, plantillas y productos
export MIGRATE_MODEL=product.category,product.template,product.product
python3 migrate.py

# Migrar todos los modelos de productos
export MIGRATE_MODEL=product.category,product.template,product.product,product.pricelist,product.pricelist.item
python3 migrate.py
```

## ⚠️ Notas

- Los espacios alrededor de las comas se limpian automáticamente
- Si un modelo no está en `models_to_migrate.txt`, se usa `allow_many2one=False` por defecto
- El orden de migración respeta las dependencias si los modelos están relacionados
- Si no se especifica `MIGRATE_MODEL`, se migran todos los modelos de `models_to_migrate.txt`

## ✅ Cambios en el Código

**Archivo:** `migrate.py`
**Líneas:** 5390-5435

**Cambios principales:**
- `single_model` → `migrate_models` (lista)
- Soporte para parsear múltiples modelos separados por comas
- Configuración individual de `allow_many2one` por modelo
- Logging mejorado para mostrar cuántos modelos se migrarán

