# Plan de Migración CRM: Odoo v13 → v18

## 📋 Resumen Ejecutivo

Este documento describe el plan completo para migrar los módulos de CRM desde Odoo v13 a v18 utilizando el script de migración XML-RPC.

## 🎯 Objetivos

- Migrar todos los datos de CRM manteniendo la integridad referencial
- Preservar relaciones entre oportunidades, equipos, contactos y usuarios
- Mantener el historial y estados de las oportunidades
- Asegurar que las relaciones many2many se migren correctamente

## 📦 Modelos CRM a Migrar

### Modelos Principales (en orden de dependencias)

1. **crm.tag** (Etiquetas CRM)
   - Sin dependencias críticas
   - Relaciones: many2many con crm.lead
   - Configuración: `crm.tag:True`

2. **crm.stage** (Etapas del Pipeline)
   - Depende de: crm.team (team_id)
   - Relaciones: many2one con crm.team
   - Configuración: `crm.stage:True`

3. **crm.team** (Equipos de Ventas)
   - Depende de: res.users (user_id, member_ids)
   - Relaciones: many2one con res.users, many2many con res.users
   - Configuración: `crm.team:True`
   - **Nota**: Asegurar que res.users ya esté migrado

4. **crm.lost.reason** (Razones de Pérdida)
   - Sin dependencias críticas
   - Relaciones: many2one con crm.lead (cuando se pierde)
   - Configuración: `crm.lost.reason:True`

5. **crm.lead** (Oportunidades/Leads)
   - Depende de: 
     - res.partner (partner_id)
     - crm.team (team_id)
     - crm.stage (stage_id)
     - res.users (user_id, create_uid, write_uid)
     - crm.lost.reason (lost_reason_id, opcional)
   - Relaciones: 
     - many2one: partner_id, team_id, stage_id, user_id, lost_reason_id
     - many2many: tag_ids (con crm.tag)
   - Configuración: `crm.lead:True`
   - **Nota**: Este es el modelo más complejo, migrar al final

### Modelos Secundarios (Opcionales)

6. **crm.merge.opportunity** (Fusiones de Oportunidades)
   - Depende de: crm.lead
   - Configuración: `crm.merge.opportunity:False` (solo si es necesario)

## 📝 Configuración del Archivo `models_to_migrate.txt`

```txt
# ============================================
# MIGRACIÓN CRM: Odoo v13 → v18
# ============================================
# Orden de migración (respetar dependencias):
# 1. Etiquetas (sin dependencias)
# 2. Razones de pérdida (sin dependencias)
# 3. Equipos de ventas (depende de res.users)
# 4. Etapas del pipeline (depende de crm.team)
# 5. Oportunidades/Leads (depende de todo lo anterior)

# PREREQUISITOS (deben estar migrados antes):
# res.partner:True
# res.users:True

# MODELOS CRM
crm.tag:True
crm.lost.reason:True
crm.team:True
crm.stage:True
crm.lead:True
```

## 🔧 Configuraciones Especiales

### 1. Archivo `exceptions/field_mappings.json`

```json
{
  "crm.lead": {
    "type": {
      "lead": "opportunity",
      "opportunity": "opportunity",
      "default": "opportunity",
      "description": "En v18, 'lead' y 'opportunity' se unifican. Mapear ambos a 'opportunity'"
    },
    "probability": {
      "description": "Campo probability puede tener valores diferentes en v18. Verificar rangos."
    }
  },
  "crm.stage": {
    "type": {
      "lead": "lead",
      "opportunity": "opportunity",
      "default": "lead",
      "description": "Tipo de etapa. Verificar compatibilidad con v18"
    }
  }
}
```

### 2. Archivo `exceptions/m2m_fields.json`

```json
{
  "crm.lead": {
    "tag_ids": {
      "description": "Etiquetas CRM para oportunidades. Relación many2many con crm.tag"
    }
  },
  "crm.team": {
    "member_ids": {
      "description": "Miembros del equipo de ventas. Relación many2many con res.users"
    }
  }
}
```

### 3. Archivo `exceptions/m2o_fields_by_name.json`

```json
{
  "crm.lead": {
    "lost_reason_id": {
      "model": "crm.lost.reason",
      "search_field": "name",
      "create_if_not_exists": false,
      "description": "Razón de pérdida de oportunidad. Solo buscar, no crear."
    }
  },
  "crm.stage": {
    "team_id": {
      "model": "crm.team",
      "search_field": "name",
      "create_if_not_exists": false,
      "description": "Equipo de ventas para la etapa. Solo buscar, no crear."
    }
  }
}
```

## ⚠️ Consideraciones Importantes

### Campos que Pueden Requerir Transformación

1. **crm.lead.type**:
   - En v13: 'lead' o 'opportunity'
   - En v18: Puede haber cambios en la estructura
   - **Acción**: Verificar y mapear según `field_mappings.json`

2. **crm.lead.probability**:
   - En v13: 0-100
   - En v18: Verificar si el rango es el mismo
   - **Acción**: Validar valores antes de migrar

3. **crm.stage.sequence**:
   - Orden de las etapas en el pipeline
   - **Acción**: Asegurar que se migre correctamente para mantener el orden

4. **crm.team.member_ids**:
   - Relación many2many con res.users
   - **Acción**: Aplicar después de migrar crm.team y res.users

5. **crm.lead.tag_ids**:
   - Relación many2many con crm.tag
   - **Acción**: Aplicar después de migrar crm.lead y crm.tag

### Campos Computados/No Almacenados (NO se migran)

- `crm.lead.planned_revenue` (si es computed)
- `crm.lead.expected_revenue` (si es computed)
- `crm.lead.date_deadline` (si es computed)
- Campos de sistema: `create_uid`, `write_uid`, `create_date`, `write_date`

### Campos One2many (NO se migran directamente)

- `crm.lead.activity_ids` (actividades)
- `crm.lead.message_ids` (mensajes/notas)
- `crm.lead.order_ids` (pedidos relacionados, si existe)

**Nota**: Estos campos se pueden migrar por separado si es necesario.

## 📊 Orden de Ejecución Recomendado

### Fase 1: Preparación
1. ✅ Verificar que `res.partner` y `res.users` estén migrados
2. ✅ Crear archivos de configuración en `exceptions/`
3. ✅ Actualizar `models_to_migrate.txt` con modelos CRM

### Fase 2: Migración de Modelos Base
1. **crm.tag** (sin dependencias)
2. **crm.lost.reason** (sin dependencias)
3. **crm.team** (depende de res.users)

### Fase 3: Migración de Modelos Dependientes
4. **crm.stage** (depende de crm.team)
5. **crm.lead** (depende de todo lo anterior)

### Fase 4: Aplicación de Relaciones Many2many
- Aplicar `crm.team.member_ids` (después de migrar crm.team)
- Aplicar `crm.lead.tag_ids` (después de migrar crm.lead)

## 🔍 Validaciones Post-Migración

### Verificaciones a Realizar

1. **Conteo de Registros**:
   ```sql
   -- En v13
   SELECT COUNT(*) FROM crm_lead;
   
   -- En v18 (usando migration.tracking)
   SELECT COUNT(*) FROM migration_tracking WHERE model_name = 'crm.lead';
   ```

2. **Integridad Referencial**:
   - Verificar que todas las oportunidades tengan partner_id válido
   - Verificar que todas las etapas tengan team_id válido
   - Verificar que todas las oportunidades tengan stage_id válido

3. **Relaciones Many2many**:
   - Verificar que las etiquetas se aplicaron correctamente a las oportunidades
   - Verificar que los miembros se asignaron correctamente a los equipos

4. **Campos Críticos**:
   - Verificar que los montos (expected_revenue, planned_revenue) se migraron
   - Verificar que las fechas (date_deadline, date_open, date_closed) se migraron
   - Verificar que las probabilidades se migraron correctamente

## 🚀 Comandos de Ejecución

### 1. Modo Test (Recomendado primero)

```bash
# Configurar modo test en .env
TEST_MODE=True

# Ejecutar migración
python3 migrate.py
```

### 2. Modo Producción

```bash
# Configurar modo producción en .env
TEST_MODE=False

# Ejecutar migración
python3 migrate.py
```

## 📁 Estructura de Archivos Esperada

Después de la migración, deberías tener:

```
imports/
├── import_crm_tag.json
├── import_crm_lost_reason.json
├── import_crm_team.json
├── import_crm_stage.json
├── import_crm_lead.json
├── import_crm_team_res_users.json (many2many)
└── import_crm_lead_crm_tag.json (many2many)

logs/
└── migration_YYYYMMDD_HHMMSS.log

errors/
├── errors_crm_tag.json (si hay errores)
├── errors_crm_lead.json (si hay errores)
└── ...
```

## 🐛 Solución de Problemas Comunes

### Problema: "Oportunidad sin partner_id"
**Solución**: Verificar que res.partner esté migrado antes de crm.lead

### Problema: "Etapa sin team_id"
**Solución**: Verificar que crm.team esté migrado antes de crm.stage

### Problema: "Etiquetas no se aplican"
**Solución**: Verificar que crm.tag esté migrado y que la relación many2many se aplique después

### Problema: "Probabilidad fuera de rango"
**Solución**: Agregar validación en `field_mappings.json` o ajustar valores

## 📚 Referencias

- [Documentación Odoo CRM](https://www.odoo.com/documentation/)
- Script de migración: `migrate.py`
- Configuración: `models_to_migrate.txt`, `exceptions/`

## ✅ Checklist Final

- [ ] res.partner migrado
- [ ] res.users migrado
- [ ] Archivos de configuración creados en `exceptions/`
- [ ] `models_to_migrate.txt` actualizado
- [ ] Modo test ejecutado exitosamente
- [ ] Validaciones post-migración realizadas
- [ ] Relaciones many2many verificadas
- [ ] Logs revisados para errores
- [ ] Migración en producción ejecutada

---

**Fecha de Creación**: 2026-01-08  
**Versión**: 1.0  
**Autor**: andyengit

