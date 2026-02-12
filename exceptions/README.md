# Excepciones de Campos

Esta carpeta contiene configuraciones para manejar transformaciones de campos durante la migración.

## Archivo: `field_mappings.json`

Este archivo permite mapear valores de campos que han cambiado entre v13 y v18.

### Formato

```json
{
  "modelo": {
    "campo": {
      "valor_v13": "valor_v18",
      "otro_valor_v13": "otro_valor_v18",
      "default": "valor_por_defecto",
      "description": "Descripción del mapeo"
    }
  }
}
```

### Ejemplo

Para `res.partner.type` donde el valor `'company'` en v13 debe mapearse a `'contact'` en v18:

```json
{
  "res.partner": {
    "type": {
      "company": "contact",
      "default": "contact",
      "description": "Mapeo de valores para res.partner.type. En v18, 'company' ya no existe, se mapea a 'contact'"
    }
  }
}
```

### Características

- **Mapeo directo**: Si el valor de v13 está en el mapeo, se reemplaza por el valor de v18
- **Valor por defecto**: Si un valor no está en el mapeo y existe `default`, se usa ese valor
- **Descripción**: Campo opcional para documentar el mapeo

### Agregar nuevos mapeos

1. Edita `field_mappings.json`
2. Agrega el modelo y campo correspondiente
3. Define los mapeos de valores
4. El script aplicará automáticamente estos mapeos durante la preparación de registros


