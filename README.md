# Script de Migración Odoo v13 a v18

Script para migrar datos de Odoo v13 a v18 usando XML-RPC.

## Características

- ✅ Solo lectura en v13 (no modifica la base de datos v13)
- ✅ Migración en batches de al menos 100 registros
- ✅ Exportación de datos a JSON
- ✅ Solo campos almacenados (no one2many)
- ✅ Many2one solo si está especificado
- ✅ Uso de `migrate_batch` del módulo `migration_tracking`
- ✅ Detección automática de duplicados
- ✅ Tracking completo de migraciones en `migration.tracking`

## Requisitos

- Python 3.6+
- Acceso XML-RPC a Odoo v13 y v18
- Módulo `migration_tracking` instalado en v18

## Configuración

1. Copia `.env.example` a `.env` y configura las variables:

```bash
cp .env.example .env
```

2. Edita `.env` con tus credenciales:

```env
V13_URL=http://localhost:8069
V13_DB=odoo13
V13_USERNAME=admin
V13_PASSWORD=admin

V18_URL=http://localhost:8069
V18_DB=odoo18
V18_USERNAME=admin
V18_PASSWORD=admin

BATCH_SIZE=100
```

## Uso

### Opción 1: Usar archivo de texto (Recomendado)

Edita el archivo `models_to_migrate.txt` y agrega los modelos a migrar, uno por línea:

```
res.partner:True
product.product:False
res.users:True
```

Formato:
- `modelo:True` - Incluye campos many2one
- `modelo:False` - No incluye campos many2one
- `modelo` - Por defecto False (no incluye many2one)
- Las líneas que empiezan con `#` son comentarios

Luego ejecuta:

```bash
python3 migrate.py
```

### Opción 2: Usar el script de ejemplo

Copia y modifica `example_migration.py`:

```bash
cp example_migration.py my_migration.py
# Edita my_migration.py con tus modelos
python3 my_migration.py
```

## Configuración de Modelos

### Formato del archivo de texto

Cada línea en `models_to_migrate.txt` puede tener:

- `modelo:True` - Incluye campos many2one
- `modelo:False` - No incluye campos many2one  
- `modelo` - Por defecto False (no incluye many2one)

Ejemplos:

```
# Modelos con many2one
res.partner:True
res.users:True

# Modelos sin many2one
product.product:False
sale.order:False

# Por defecto sin many2one
account.move
```

### Variables de entorno

Puedes especificar un archivo diferente usando la variable de entorno `MODELS_FILE`:

```bash
export MODELS_FILE=mis_modelos.txt
python3 migrate.py
```

**Migrar modelos específicos:**

Para probar o migrar rápidamente uno o más modelos específicos, usa la variable de entorno `MIGRATE_MODEL`:

```bash
# Migrar un solo modelo
export MIGRATE_MODEL=crm.team
python3 migrate.py

# Migrar múltiples modelos separados por comas
export MIGRATE_MODEL=product.category,product.template,product.product
python3 migrate.py
```

Esto migrará solo los modelos especificados (y sus dependencias si es necesario). El script intentará determinar `allow_many2one` desde el archivo `models_to_migrate.txt` si existe, o usará `False` por defecto.

**Modo test:**

Para ejecutar en modo test (sin crear registros en v18):

```bash
export TEST_MODE=True
python3 migrate.py
```

## Campos Migrados

El script solo migra:

- ✅ Campos almacenados (store=True)
- ✅ Campos simples (char, integer, float, boolean, date, datetime, text)
- ✅ Campos many2one (solo si `allow_many2one=True`)
- ❌ Campos one2many (nunca)
- ❌ Campos many2many (nunca)
- ❌ Campos computed sin store (nunca)
- ❌ Campos de sistema (id, create_uid, write_uid, create_date, write_date)

## Estructura de Archivos

- `migrate.py`: Script principal de migración
- `example_migration.py`: Ejemplo de uso
- `.env.example`: Plantilla de configuración
- `.env`: Configuración real (no se sube a git)
- `migration_data/`: Directorio donde se guardan los JSON exportados
- `.gitignore`: Archivos a ignorar en git

## Flujo de Migración

1. **Análisis de Dependencias**: Detecta relaciones many2one entre modelos
2. **Ordenamiento**: Ordena modelos por dependencias (topological sort)
3. **Exportación**: Lee datos de v13 en batches y los guarda en JSON
4. **Migración por Orden**:
   - Primero se migran modelos sin dependencias
   - Luego se migran modelos que dependen de los anteriores
5. **Mapeo de IDs**: 
   - Después de migrar cada modelo, se consulta `migration.tracking` para obtener el mapeo v13_id -> v18_id
   - Antes de crear registros con many2one, se reemplazan los IDs de v13 por los IDs de v18
6. **Creación**: Crea registros en v18 usando `migrate_batch` en batches
7. **Tracking**: Registra el mapeo v13_id -> v18_id en `migration.tracking`

### Ejemplo de Flujo

Si tienes:
- `res.partner.category` (sin dependencias)
- `res.partner` (depende de `res.partner.category` vía campo `category_id`)

El script:
1. Migra primero `res.partner.category` (v13 id=1 -> v18 id=8)
2. Consulta `migration.tracking` y obtiene el mapeo
3. Migra `res.partner` reemplazando `category_id=1` por `category_id=8` antes de crear

## Notas Importantes

- El script **NUNCA** modifica la base de datos v13 (solo lectura)
- Los duplicados se detectan automáticamente usando `migration.tracking`
- Los datos exportados se guardan en JSON para poder reutilizarlos
- El tamaño de batch mínimo es 100 (configurable en BATCH_SIZE)

# mig2
# mig2
# mig2 git init git add README.md git commit -m first commit git branch -M main git remote add originagi git@github:andyclodofy/mig2.git git push -u origin main
