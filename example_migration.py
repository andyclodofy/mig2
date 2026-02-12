#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ejemplo de uso del script de migración.

Este archivo muestra cómo usar el script de migración para migrar modelos específicos.
Copia este archivo y modifícalo según tus necesidades.
"""

from migrate import MigrationScript
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def example_migration():
    """Ejemplo de migración de modelos"""
    
    script = MigrationScript()
    
    try:
        # Cargar configuración desde .env o variables de entorno
        script.load_env()
        
        # ============================================
        # ESPECIFICA AQUÍ LOS MODELOS A MIGRAR
        # ============================================
        models_to_migrate = [
            {
                'model': 'res.partner',
                'allow_many2one': True,  # Incluir campos many2one como parent_id
                'json_file': None  # None = exportar primero desde v13
            },
            {
                'model': 'product.product',
                'allow_many2one': False,  # No incluir campos many2one
                'json_file': None
            },
            # Si ya exportaste datos previamente, puedes usar el JSON:
            # {
            #     'model': 'res.users',
            #     'allow_many2one': True,
            #     'json_file': 'migration_data/res_users_20240101_120000.json'
            # },
        ]
        
        # Ejecutar migración para cada modelo
        total_stats = {
            'created': 0,
            'skipped': 0,
            'errors': 0,
            'total': 0
        }
        
        for model_config in models_to_migrate:
            model = model_config.get('model')
            allow_many2one = model_config.get('allow_many2one', False)
            json_file = model_config.get('json_file', None)
            
            logger.info(f"\n{'='*60}")
            logger.info(f"Migrando modelo: {model}")
            logger.info(f"Allow many2one: {allow_many2one}")
            logger.info(f"{'='*60}\n")
            
            try:
                stats = script.migrate_model(model, json_file, allow_many2one)
                
                if 'error' not in stats:
                    total_stats['created'] += stats.get('created', 0)
                    total_stats['skipped'] += stats.get('skipped', 0)
                    total_stats['errors'] += stats.get('errors', 0)
                    total_stats['total'] += stats.get('total', 0)
                else:
                    logger.error(f"Error en {model}: {stats.get('error')}")
                    
            except Exception as e:
                logger.error(f"✗ Error migrando {model}: {e}")
                import traceback
                traceback.print_exc()
        
        # Resumen final
        logger.info("\n" + "=" * 60)
        logger.info("RESUMEN TOTAL DE MIGRACIÓN:")
        logger.info(f"  ✓ Creados: {total_stats['created']}")
        logger.info(f"  ⊘ Omitidos (duplicados): {total_stats['skipped']}")
        logger.info(f"  ✗ Errores: {total_stats['errors']}")
        logger.info(f"  📊 Total procesados: {total_stats['total']}")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"✗ Error fatal en migración: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == '__main__':
    example_migration()

