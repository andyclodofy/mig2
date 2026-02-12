#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de migración de datos de Odoo v13 a v18 usando XML-RPC.

Este script:
- Lee datos de v13 (solo lectura)
- Almacena datos en JSON
- Migra datos a v18 usando batches de al menos 100 registros
- Solo importa campos almacenados (no one2many, many2one solo si está especificado)
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Any
import xmlrpc.client
import socket


class TimeoutServerProxy(xmlrpc.client.ServerProxy):
    """ServerProxy con timeout configurable para evitar bloqueos"""
    
    def __init__(self, uri, timeout=300, **kwargs):
        self._timeout = timeout
        super().__init__(uri, **kwargs)
    
    def __getattr__(self, name):
        # Establecer timeout antes de cada llamada
        socket.setdefaulttimeout(self._timeout)
        return super().__getattr__(name)


def setup_logging(log_dir: str = 'logs'):
    """
    Configura el sistema de logging con múltiples handlers:
    - Consola: Solo muestra progreso (mensajes con [PROGRESO])
    - Archivo completo: Todos los logs (info, warning, error, debug)
    - Archivo de debug: Solo logs de debug
    - Archivo de errores: Solo errores y warnings detallados
    
    Args:
        log_dir: Directorio donde se guardarán los logs
    """
    os.makedirs(log_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = os.path.join(log_dir, f'migration_{timestamp}.log')
    debug_file = os.path.join(log_dir, f'debug_{timestamp}.log')
    error_file = os.path.join(log_dir, f'errors_{timestamp}.log')
    
    # Configurar formato
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    detailed_format = '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    
    # Configurar logger principal
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # Nivel más bajo para capturar todo
    
    # Limpiar handlers existentes
    logger.handlers = []
    
    # Handler 1: Archivo completo (todos los logs)
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format, date_format))
    logger.addHandler(file_handler)
    
    # Handler 2: Archivo de debug (solo debug)
    debug_handler = logging.FileHandler(debug_file, encoding='utf-8')
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.addFilter(lambda record: record.levelno == logging.DEBUG)
    debug_handler.setFormatter(logging.Formatter(detailed_format, date_format))
    logger.addHandler(debug_handler)
    
    # Handler 3: Archivo de errores (solo errores y warnings, con detalles)
    error_handler = logging.FileHandler(error_file, encoding='utf-8')
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(logging.Formatter(detailed_format, date_format))
    logger.addHandler(error_handler)
    
    # Handler 4: Consola (todos los mensajes INFO y superiores en tiempo real)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)  # Mostrar INFO, WARNING, ERROR, CRITICAL
    # Formato con timestamp para consola
    console_format = '%(asctime)s - %(levelname)s - %(message)s'
    console_handler.setFormatter(logging.Formatter(console_format, date_format))
    logger.addHandler(console_handler)
    
    return logger, log_file, debug_file, error_file

logger, log_file, debug_file, error_file = setup_logging()


class OdooConnection:
    """Clase para manejar conexiones XML-RPC con Odoo"""
    
    def __init__(self, url: str, db: str, username: str, password: str):
        self.url = url
        self.db = db
        self.username = username
        self.password = password
        self.uid = None
        self.models = None
        self._connect()
    
    def _connect(self):
        """Establece conexión con Odoo"""
        try:
            # Crear ServerProxy con timeout de 5 minutos para operaciones largas como migrate_batch
            # Usar TimeoutServerProxy para evitar bloqueos infinitos
            common = TimeoutServerProxy(f'{self.url}/xmlrpc/2/common', timeout=300, allow_none=True)
            self.uid = common.authenticate(self.db, self.username, self.password, {})
            
            if not self.uid:
                raise Exception("Error de autenticación")
            
            # Para el proxy de modelos, usar timeout de 5 minutos (300 segundos)
            self.models = TimeoutServerProxy(f'{self.url}/xmlrpc/2/object', timeout=300, allow_none=True)
            logger.info(f"✓ Conectado a {self.url} (DB: {self.db}, User: {self.username})")
        except Exception as e:
            logger.error(f"✗ Error conectando a {self.url}: {e}")
            raise
    
    def search_read(self, model: str, domain: List, fields: List[str], 
                   limit: int = None, offset: int = 0, order: str = None, 
                   context: Dict = None) -> List[Dict]:
        """Lee registros de un modelo"""
        try:
            kwargs = {}
            if limit:
                kwargs['limit'] = limit
            if offset:
                kwargs['offset'] = offset
            if order:
                kwargs['order'] = order
            if context:
                kwargs['context'] = context
            
            return self.models.execute_kw(
                self.db, self.uid, self.password,
                model, 'search_read',
                [domain],
                {'fields': fields, **kwargs}
            )
        except Exception as e:
            logger.error(f"✗ Error leyendo {model}: {e}")
            raise
    
    def count_records(self, model: str, domain: List = None, context: Dict = None) -> int:
        """
        Cuenta registros de un modelo.
        
        Args:
            model: Nombre del modelo
            domain: Dominio de búsqueda (opcional)
            context: Contexto de Odoo (opcional, para incluir registros archivados con active_test=False)
        
        Returns:
            Número de registros
        """
        try:
            if domain is None:
                domain = []
            
            kwargs = {}
            if context:
                kwargs['context'] = context
            
            return self.models.execute_kw(
                self.db, self.uid, self.password,
                model, 'search_count',
                [domain],
                kwargs
            )
        except Exception as e:
            logger.warning(f"⚠ No se pudo contar registros de {model}: {e}")
            return 0
    
    def get_fields(self, model: str) -> Dict[str, Any]:
        """Obtiene información de campos de un modelo usando fields_get"""
        try:
            return self.models.execute_kw(
                self.db, self.uid, self.password,
                model, 'fields_get',
                [],
                {'attributes': ['type', 'string', 'store', 'readonly', 'required', 'relation', 'relation_table']}
            )
        except Exception as e:
            logger.warning(f"⚠ No se pudo obtener campos de {model}: {e}")
            return {}
    
    def get_table_info(self, table_name: str) -> Dict[str, Any]:
        """
        Intenta obtener información de una tabla intermedia many2many.
        Retorna información sobre los campos disponibles.
        
        Args:
            table_name: Nombre de la tabla intermedia
        
        Returns:
            Diccionario con información de la tabla: {'accessible': bool, 'fields': List[str], 'sample': Dict}
        """
        result = {
            'accessible': False,
            'fields': [],
            'sample': None,
            'error': None
        }
        
        try:
            # Intentar obtener campos usando fields_get
            fields_info = self.get_fields(table_name)
            if fields_info:
                result['accessible'] = True
                result['fields'] = list(fields_info.keys())
                logger.debug(f"[TABLE INFO] Tabla {table_name} accesible como modelo con {len(result['fields'])} campos")
                return result
        except Exception as e1:
            logger.debug(f"[TABLE INFO] No se pudo acceder a {table_name} con fields_get: {e1}")
        
        try:
            # Intentar leer un registro de muestra para obtener campos
            sample = self.search_read(
                table_name,
                [],
                [],  # Lista vacía = todos los campos
                limit=1
            )
            if sample and len(sample) > 0:
                result['accessible'] = True
                result['fields'] = list(sample[0].keys())
                result['sample'] = sample[0]
                logger.debug(f"[TABLE INFO] Tabla {table_name} accesible, campos obtenidos desde muestra: {result['fields']}")
                return result
        except Exception as e2:
            logger.debug(f"[TABLE INFO] No se pudo leer muestra de {table_name}: {e2}")
            result['error'] = str(e2)
        
        # Si no es accesible, intentar construir campos esperados
        logger.debug(f"[TABLE INFO] Tabla {table_name} no accesible directamente como modelo")
        return result
    
    def create(self, model: str, records: List[Dict]) -> List[int]:
        """Crea registros en un modelo (solo para v18)"""
        try:
            if not records:
                return []
            
            # Validación final antes de enviar a XML-RPC
            cleaned_records = []
            for idx, record in enumerate(records):
                cleaned_record = {}
                for field_name, field_value in record.items():
                    # Validar tipos para XML-RPC
                    if field_value is None:
                        # Omitir None (no es válido en XML-RPC)
                        continue
                    elif isinstance(field_value, (bool, int, float, str)):
                        # Tipos válidos para XML-RPC
                        cleaned_record[field_name] = field_value
                    elif isinstance(field_value, (list, tuple, dict)):
                        # Estructuras complejas no son válidas
                        logger.warning(f"[CREATE] Campo {field_name} en registro {idx+1} tiene tipo complejo {type(field_value)}, omitiendo")
                        continue
                    else:
                        # Convertir a string como último recurso
                        logger.warning(f"[CREATE] Campo {field_name} en registro {idx+1} tiene tipo {type(field_value)}, convirtiendo a string")
                        cleaned_record[field_name] = str(field_value)
                
                if cleaned_record:
                    cleaned_records.append(cleaned_record)
                else:
                    logger.error(f"[CREATE] Registro {idx+1} quedó vacío después de limpieza, omitiendo")
            
            if not cleaned_records:
                logger.error("[CREATE] No hay registros válidos después de limpieza")
                return []
            
            # Log del primer registro para debugging
            import json
            logger.info(f"[CREATE] Enviando {len(cleaned_records)} registros a {model}")
            logger.info(f"[CREATE] Primer registro: {json.dumps(cleaned_records[0], indent=2, ensure_ascii=False, default=str)}")
            
            # Verificar tipos de todos los campos del primer registro
            logger.info("[CREATE] Tipos de campos del primer registro:")
            for field_name, field_value in cleaned_records[0].items():
                logger.info(f"[CREATE]   {field_name}: {type(field_value).__name__} = {repr(field_value)}")
            
            # Validación final: asegurar que cleaned_records es una lista de diccionarios
            if not isinstance(cleaned_records, list):
                raise ValueError(f"cleaned_records debe ser una lista, se recibió: {type(cleaned_records)}")
            
            for idx, record in enumerate(cleaned_records):
                if not isinstance(record, dict):
                    raise ValueError(f"Registro {idx+1} no es un diccionario: {type(record)}")
                if not record:
                    raise ValueError(f"Registro {idx+1} está vacío")
            
            # Odoo create() espera una lista de diccionarios como primer argumento
            # El formato correcto es: execute_kw(db, uid, password, model, 'create', [records])
            # donde records es una lista de diccionarios
            try:
                # Intentar serializar a JSON para verificar que los datos son válidos
                import json
                json.dumps(cleaned_records, default=str)
            except Exception as json_error:
                logger.error(f"[CREATE] Error serializando datos a JSON: {json_error}")
                logger.error(f"[CREATE] Datos problemáticos: {cleaned_records[:1] if cleaned_records else 'No hay datos'}")
                raise ValueError(f"Los datos no son serializables a JSON: {json_error}")
            
            # Llamar a create con el formato correcto
            # Los campos many2one ya están mapeados (IDs de v13 -> v18) antes de llegar aquí
            # por lo que podemos crear los registros directamente con todos los campos
            logger.info(f"[CREATE] >>> execute_kw({model}, 'create', [{len(cleaned_records)} registros])...")
            
            # Reintentos para errores de conexión
            max_retries = 3
            retry_delay = 5  # segundos
            
            for attempt in range(max_retries):
                try:
                    result = self.models.execute_kw(
                        self.db, self.uid, self.password,
                        model, 'create',
                        [cleaned_records]
                    )
                    logger.info(f"[CREATE] <<< execute_kw completado, {len(result)} IDs retornados")
                    return result
                except Exception as e:
                    error_str = str(e).lower()
                    is_connection_error = (
                        'broken pipe' in error_str or 
                        'connection reset' in error_str or
                        'connection' in error_str and ('refused' in error_str or 'reset' in error_str or 'closed' in error_str)
                    )
                    is_concurrency_error = (
                        'serialize access' in error_str or
                        'concurrent update' in error_str or
                        'could not serialize' in error_str
                    )
                    
                    if is_connection_error and attempt < max_retries - 1:
                        logger.warning(f"[CREATE] ⚠ Error de conexión (intento {attempt + 1}/{max_retries}): {e}")
                        logger.info(f"[CREATE] Reintentando en {retry_delay} segundos...")
                        import time
                        time.sleep(retry_delay)
                        # Reconectar
                        try:
                            self._connect()
                        except Exception as reconnect_error:
                            logger.error(f"[CREATE] ✗ Error reconectando: {reconnect_error}")
                        continue
                    elif is_concurrency_error:
                        logger.warning(f"[CREATE] ⚠ Error de concurrencia detectado: {e}")
                        logger.info(f"[CREATE] Reintentando en {retry_delay * 2} segundos...")
                        import time
                        time.sleep(retry_delay * 2)
                        if attempt < max_retries - 1:
                            continue
                        else:
                            logger.error(f"[CREATE] ✗ Error de concurrencia después de {max_retries} intentos")
                            raise
                    else:
                        logger.error(f"[CREATE] ✗ Error creando registros en {model}: {e}")
                        import traceback
                        logger.error(f"[CREATE] Traceback: {traceback.format_exc()}")
                        raise
            
            # Si llegamos aquí, todos los reintentos fallaron
            raise Exception(f"Error creando registros después de {max_retries} intentos")
        except Exception as e:
            logger.error(f"✗ Error creando registros en {model}: {e}")
            import traceback
            logger.error(f"[CREATE] Traceback: {traceback.format_exc()}")
            raise
    
    def migrate_batch(self, model: str, records_data: List[Dict], 
                     v13_ids: List[int], batch_id: str = None) -> Dict:
        """
        Migra un batch de registros usando el método migrate_batch del modelo.
        Si el método no existe, usa create estándar y registra en migration.tracking.
        """
        # Validación previa: asegurar que records_data sea una lista de diccionarios válidos
        if not isinstance(records_data, list):
            logger.error(f"[MIGRATE_BATCH] records_data no es una lista: {type(records_data)}")
            raise ValueError(f"records_data debe ser una lista, se recibió: {type(records_data)}")
        
        # Validar cada registro
        for idx, record in enumerate(records_data):
            if not isinstance(record, dict):
                logger.error(f"[MIGRATE_BATCH] Registro {idx} no es un diccionario: {type(record)}")
                raise ValueError(f"Todos los registros deben ser diccionarios, registro {idx} es: {type(record)}")
            
            # Validar que todos los valores sean tipos válidos para XML-RPC
            for field_name, field_value in record.items():
                if not isinstance(field_value, (str, int, float, bool, type(None))):
                    logger.error(f"[MIGRATE_BATCH] Registro {idx}, campo {field_name} tiene tipo inválido: {type(field_value)}")
                    logger.error(f"[MIGRATE_BATCH] Valor: {field_value}")
                    raise ValueError(f"Campo {field_name} en registro {idx} tiene tipo inválido: {type(field_value)}")
        
        # Validar v13_ids
        if not isinstance(v13_ids, list):
            logger.error(f"[MIGRATE_BATCH] v13_ids no es una lista: {type(v13_ids)}")
            raise ValueError(f"v13_ids debe ser una lista, se recibió: {type(v13_ids)}")
        
        if len(records_data) != len(v13_ids):
            logger.error(f"[MIGRATE_BATCH] Desajuste: {len(records_data)} registros vs {len(v13_ids)} IDs")
            raise ValueError(f"El número de registros ({len(records_data)}) debe coincidir con el número de v13_ids ({len(v13_ids)})")
        
        try:
            logger.debug(f"[MIGRATE_BATCH] Llamando a migrate_batch con {len(records_data)} registros")
            
            # Log detallado antes de llamar
            import json
            logger.debug(f"[MIGRATE_BATCH] Tipo de records_data: {type(records_data)}")
            logger.debug(f"[MIGRATE_BATCH] Tipo de v13_ids: {type(v13_ids)}")
            if records_data:
                logger.debug(f"[MIGRATE_BATCH] Primer registro tipo: {type(records_data[0])}")
                logger.debug(f"[MIGRATE_BATCH] Primer registro: {json.dumps(records_data[0], indent=2, ensure_ascii=False, default=str)}")
            
            # Validar que records_data sea una lista de diccionarios
            if not isinstance(records_data, list):
                raise ValueError(f"records_data debe ser una lista, se recibió: {type(records_data)}")
            
            # Validar que cada registro sea un diccionario
            for idx, record in enumerate(records_data):
                if not isinstance(record, dict):
                    raise ValueError(f"Registro {idx} no es un diccionario: {type(record)}")
            
            # Log antes de la llamada
            logger.info(f"[MIGRATE_BATCH] Enviando {len(records_data)} registros a {model}...")
            import time
            start_time = time.time()
            
            # Llamar directamente - XML-RPC es síncrono y bloquea hasta recibir respuesta
            # Establecer timeout de socket antes de la llamada para evitar bloqueos infinitos
            logger.debug(f"[MIGRATE_BATCH] Llamando a execute_kw - timestamp: {time.time()}")
            logger.debug(f"[MIGRATE_BATCH] Modelo: {model}, Registros: {len(records_data)}, IDs: {len(v13_ids)}")
            
            # Establecer timeout de socket
            # Usar timeout corto (10s) para activar verificación alternativa rápidamente en todos los modelos
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(10)  # 10 segundos para todos los modelos
            logger.info(f"[MIGRATE_BATCH] Timeout configurado a 10 segundos para {model} (con verificación alternativa cada 10s)")
            
            # Flush logs antes de la llamada para asegurar que se escriban
            import sys
            sys.stdout.flush()
            sys.stderr.flush()
            for handler in logging.getLogger().handlers:
                handler.flush()
            
            try:
                # Usar verificación alternativa para todos los modelos: verificar cada 10 segundos
                logger.info(f"[MIGRATE_BATCH] >>> Iniciando execute_kw para {model} (con verificación alternativa cada 10s)...")
                
                # Usar threading para ejecutar la llamada y verificar después de 10 segundos
                import threading
                result_container = {'result': None, 'error': None, 'completed': False}
                
                def call_migrate_batch():
                    max_retries = 3
                    retry_delay = 5
                    
                    for attempt in range(max_retries):
                        try:
                            result_container['result'] = self.models.execute_kw(
                                self.db, self.uid, self.password,
                                model, 'migrate_batch',
                                [records_data, v13_ids],
                                {'batch_id': batch_id, 'skip_duplicates': True}
                            )
                            result_container['completed'] = True
                            return
                        except Exception as e:
                            error_str = str(e).lower()
                            is_connection_error = (
                                'broken pipe' in error_str or 
                                'connection reset' in error_str or
                                'connection' in error_str and ('refused' in error_str or 'reset' in error_str or 'closed' in error_str)
                            )
                            is_concurrency_error = (
                                'serialize access' in error_str or
                                'concurrent update' in error_str or
                                'could not serialize' in error_str
                            )
                            
                            if is_connection_error and attempt < max_retries - 1:
                                logger.warning(f"[MIGRATE_BATCH] ⚠ Error de conexión (intento {attempt + 1}/{max_retries}): {e}")
                                logger.info(f"[MIGRATE_BATCH] Reintentando en {retry_delay} segundos...")
                                import time
                                time.sleep(retry_delay)
                                # Reconectar
                                try:
                                    self._connect()
                                except Exception as reconnect_error:
                                    logger.error(f"[MIGRATE_BATCH] ✗ Error reconectando: {reconnect_error}")
                                continue
                            elif is_concurrency_error and attempt < max_retries - 1:
                                logger.warning(f"[MIGRATE_BATCH] ⚠ Error de concurrencia (intento {attempt + 1}/{max_retries}): {e}")
                                logger.info(f"[MIGRATE_BATCH] Reintentando en {retry_delay * 2} segundos...")
                                import time
                                time.sleep(retry_delay * 2)
                                continue
                            else:
                                result_container['error'] = e
                                result_container['completed'] = True
                                return
                
                # Iniciar thread
                thread = threading.Thread(target=call_migrate_batch, daemon=True)
                thread.start()
                
                # Polling cada 10 segundos hasta que termine o se alcance máximo de tiempo
                max_wait_time = 300  # Máximo 5 minutos
                check_interval = 10.0  # Verificar cada 10 segundos
                elapsed = 0
                
                while not result_container['completed'] and elapsed < max_wait_time:
                    time.sleep(check_interval)
                    elapsed += check_interval
                    
                    if not result_container['completed']:
                        # Verificar en migration.tracking si el batch se completó
                        logger.info(f"[MIGRATE_BATCH] Verificando en migration.tracking si el batch {batch_id} se completó... ({elapsed:.0f}s transcurridos)")
                        verification_result = self._verify_batch_completion(model, batch_id, v13_ids)
                        
                        if verification_result:
                            # El batch se completó según migration.tracking
                            logger.info(f"[MIGRATE_BATCH] ✓ Batch completado según migration.tracking: Creados={verification_result.get('stats', {}).get('created', 0)}, Omitidos={verification_result.get('stats', {}).get('skipped', 0)}, Errores={verification_result.get('stats', {}).get('errors', 0)}")
                            result = verification_result
                            break
                        else:
                            logger.info(f"[MIGRATE_BATCH] Batch aún no encontrado en migration.tracking, continuando espera...")
                
                if not result_container['completed'] and elapsed >= max_wait_time:
                    # Timeout después de máximo tiempo, verificar una última vez
                    logger.warning(f"[MIGRATE_BATCH] Tiempo máximo alcanzado ({max_wait_time}s), verificando una última vez...")
                    result = self._verify_batch_completion(model, batch_id, v13_ids)
                    if result:
                        logger.info(f"[MIGRATE_BATCH] ✓ Batch verificado en migration.tracking: Creados={result.get('stats', {}).get('created', 0)}, Omitidos={result.get('stats', {}).get('skipped', 0)}, Errores={result.get('stats', {}).get('errors', 0)}")
                    else:
                        logger.error(f"[MIGRATE_BATCH] ✗ No se pudo verificar el batch en migration.tracking después de {max_wait_time}s")
                        raise TimeoutError(f"Timeout esperando respuesta de migrate_batch para {model} y no se pudo verificar en migration.tracking")
                elif result_container['error']:
                    raise result_container['error']
                elif result_container['completed']:
                    # La operación terminó normalmente
                    result = result_container['result']
                    logger.info(f"[MIGRATE_BATCH] <<< Respuesta recibida de execute_kw")
                    logger.debug(f"[MIGRATE_BATCH] Respuesta recibida - timestamp: {time.time()}")
                    logger.debug(f"[MIGRATE_BATCH] Tipo de resultado: {type(result)}")
            except socket.timeout:
                logger.error(f"[MIGRATE_BATCH] Timeout esperando respuesta de Odoo para {model}")
                raise TimeoutError(f"Timeout esperando respuesta de migrate_batch para {model}")
            except Exception as e:
                logger.error(f"[MIGRATE_BATCH] Error durante execute_kw: {type(e).__name__}: {e}")
                raise
            finally:
                # Restaurar timeout anterior
                socket.setdefaulttimeout(old_timeout)
            
            elapsed_time = time.time() - start_time
            logger.info(f"[MIGRATE_BATCH] ✓ Completado en {elapsed_time:.2f} segundos")
            
            # Mostrar estadísticas si están disponibles
            if result and isinstance(result, dict) and 'stats' in result:
                stats = result.get('stats', {})
                logger.info(f"[MIGRATE_BATCH] Estadísticas: Creados={stats.get('created', 0)}, Omitidos={stats.get('skipped', 0)}, Errores={stats.get('errors', 0)}")
            
            return result
        except Exception as e:
            error_str = str(e)
            logger.error(f"[MIGRATE_BATCH] Error en migrate_batch: {error_str}")
            
            # Si el error es "Expresión invalida", usar fallback directamente
            if "expresión invalida" in error_str.lower() or "debe ser un diccionario" in error_str.lower():
                logger.warning(f"[FALLBACK] Error de formato detectado en migrate_batch para {model}, usando create estándar")
                return self._migrate_batch_fallback(model, records_data, v13_ids, batch_id)
            
            # Si el método no existe, usar create estándar
            if "does not exist" in error_str or "migrate_batch" in error_str.lower():
                logger.warning(f"[FALLBACK] El método migrate_batch no existe en {model}, usando create estándar")
                return self._migrate_batch_fallback(model, records_data, v13_ids, batch_id)
            else:
                logger.error(f"✗ Error en migrate_batch para {model}: {e}")
                raise
    
    def _migrate_batch_fallback(self, model: str, records_data: List[Dict], 
                               v13_ids: List[int], batch_id: str = None) -> Dict:
        """
        Fallback: Crea registros usando create estándar y registra en migration.tracking.
        
        Args:
            model: Nombre del modelo
            records_data: Lista de registros a crear
            v13_ids: Lista de IDs v13 correspondientes
            batch_id: ID del batch
        
        Returns:
            Diccionario con estadísticas similar a migrate_batch
        """
        result = {
            'created': {},
            'skipped': {},
            'errors': {},
            'stats': {'created': 0, 'skipped': 0, 'errors': 0}
        }
        
        if not records_data:
            return result
        
        # Verificar duplicados consultando migration.tracking
        existing_mapping = self.get_migration_mapping(model)
        existing_v13_ids = set(existing_mapping.keys())
        
        records_to_create = []
        v13_ids_to_create = []
        
        for record_data, v13_id in zip(records_data, v13_ids):
            v13_id_str = str(v13_id)
            
            # Verificar si ya existe
            if v13_id_str in existing_v13_ids:
                v18_id = existing_mapping[v13_id_str]
                result['skipped'][v13_id_str] = v18_id
                result['stats']['skipped'] += 1
                continue
            
            records_to_create.append(record_data)
            v13_ids_to_create.append(v13_id)
        
        if not records_to_create:
            logger.info("[FALLBACK] Todos los registros ya existen, omitiendo creación")
            return result
        
        # LIMPIEZA DE DATOS: Convertir tuplas many2one [id, name] a solo id
        # Odoo create() espera solo el ID, no tuplas
        # También limpiar campos many2many que no deben enviarse en create()
        for record in records_to_create:
            fields_to_remove = []
            for field_name, field_value in list(record.items()):
                # Si el campo es una tupla/lista con 2 elementos (formato [id, name] de search_read)
                if isinstance(field_value, (list, tuple)) and len(field_value) >= 1:
                    # Verificar si es un many2one (tupla [id, name]) o many2many (lista de IDs)
                    if len(field_value) == 2 and isinstance(field_value[0], (int, str)):
                        # Es un many2one [id, name], convertir a solo el ID
                        record[field_name] = int(field_value[0]) if isinstance(field_value[0], str) else field_value[0]
                        logger.debug(f"[FALLBACK] Convertido many2one {field_name} de {field_value} a {record[field_name]}")
                    elif len(field_value) > 2 or (len(field_value) == 1 and isinstance(field_value[0], (int, str))):
                        # Es probablemente un many2many (lista de IDs)
                        # Los campos many2many no se pueden establecer en create(), se deben omitir
                        # Se aplicarán después usando write()
                        fields_to_remove.append(field_name)
                        logger.debug(f"[FALLBACK] Omitiendo campo many2many {field_name} (se aplicará después con write)")
                    elif len(field_value) == 0:
                        # Lista vacía, convertir a False
                        record[field_name] = False
                elif field_value is None:
                    # None no es válido para XML-RPC, convertir a False
                    record[field_name] = False
            
            # Remover campos many2many
            for field_name in fields_to_remove:
                del record[field_name]
        
        # VERIFICACIÓN FINAL CRÍTICA ANTES DE CREAR: Asegurar que todos los registros tengan 'name' válido
        if model == 'res.partner':
            for idx, record in enumerate(records_to_create):
                name_value = record.get('name')
                v13_id = v13_ids_to_create[idx] if idx < len(v13_ids_to_create) else 'Unknown'
                
                # Verificar si name está vacío, None, False, o solo espacios
                is_name_empty = (name_value is None or 
                               name_value is False or 
                               (isinstance(name_value, str) and not name_value.strip()))
                
                if is_name_empty:
                    # Forzar asignación de name
                    display_name = record.get('display_name')
                    
                    if display_name and isinstance(display_name, str) and display_name.strip():
                        record['name'] = display_name
                    else:
                        # Para res.partner, usar espacio en blanco si no hay nombre
                        record['name'] = " "
                    logger.error(f"  ✗ [FALLBACK VERIFICACIÓN FINAL] Registro {idx+1} tenía 'name' vacío (ID v13: {v13_id}), FORZADO a: {record['name']}")
                elif isinstance(name_value, str) and not name_value.strip():
                    # Solo espacios en blanco - Para res.partner, usar espacio en blanco
                    record['name'] = " "
                    logger.error(f"  ✗ [FALLBACK VERIFICACIÓN FINAL] Registro {idx+1} tenía 'name' solo espacios (ID v13: {v13_id}), FORZADO a: {record['name']}")
        
        # VALIDACIÓN FINAL: Asegurar que todos los valores sean tipos válidos para XML-RPC
        # XML-RPC solo acepta: str, int, float, bool, None (convertido a False)
        # IMPORTANTE: Mantener sincronizados records y v13_ids
        cleaned_records_to_create = []
        cleaned_v13_ids_to_create = []
        for record_idx, record in enumerate(records_to_create):
            cleaned_record = {}
            for field_name, field_value in list(record.items()):
                # Validar y convertir tipos
                if field_value is None:
                    # Omitir None (no es válido en XML-RPC)
                    continue
                elif isinstance(field_value, bool):
                    # Mantener booleanos
                    cleaned_record[field_name] = field_value
                elif isinstance(field_value, (int, float)):
                    # Mantener números
                    cleaned_record[field_name] = field_value
                elif isinstance(field_value, str):
                    # Mantener strings
                    cleaned_record[field_name] = field_value
                elif isinstance(field_value, (list, tuple, dict)):
                    # Estructuras complejas no son válidas para XML-RPC en create()
                    logger.warning(f"[FALLBACK] Removiendo campo {field_name} con tipo complejo {type(field_value)}: {field_value}")
                    continue
                else:
                    # Cualquier otro tipo, intentar convertir a string o remover
                    logger.warning(f"[FALLBACK] Campo {field_name} tiene tipo inválido {type(field_value)}, intentando convertir")
                    try:
                        cleaned_record[field_name] = str(field_value)
                    except Exception:
                        logger.warning(f"[FALLBACK] No se pudo convertir {field_name}, omitiendo")
                        continue
            
            if cleaned_record:
                cleaned_records_to_create.append(cleaned_record)
                # Mantener sincronizado el v13_id correspondiente
                cleaned_v13_ids_to_create.append(v13_ids_to_create[record_idx])
            else:
                logger.error(f"[FALLBACK] Registro {record_idx+1} quedó vacío después de limpieza, omitiendo")
        
        if not cleaned_records_to_create:
            logger.error("[FALLBACK] No hay registros válidos después de limpieza")
            return result
        
        # Reemplazar records_to_create y v13_ids_to_create con los limpiados
        records_to_create = cleaned_records_to_create
        v13_ids_to_create = cleaned_v13_ids_to_create
        
        # Log de los primeros registros antes de crear (para debugging)
        if records_to_create:
            import json
            logger.info(f"[FALLBACK] Preparando {len(records_to_create)} registros para crear en {model}")
            logger.info("[FALLBACK] Primer registro a crear:")
            logger.info(f"[FALLBACK] {json.dumps(records_to_create[0], indent=2, ensure_ascii=False, default=str)}")
            
            # Verificar tipos de todos los campos del primer registro
            logger.info("[FALLBACK] Tipos de campos del primer registro:")
            for field_name, field_value in records_to_create[0].items():
                logger.info(f"[FALLBACK]   {field_name}: {type(field_value).__name__} = {repr(field_value)}")
            
            # Validación final: asegurar que records_to_create es una lista de diccionarios
            if not isinstance(records_to_create, list):
                logger.error(f"[FALLBACK] ERROR: records_to_create no es una lista: {type(records_to_create)}")
                raise ValueError(f"records_to_create debe ser una lista, se recibió: {type(records_to_create)}")
            
            for idx, record in enumerate(records_to_create):
                if not isinstance(record, dict):
                    logger.error(f"[FALLBACK] ERROR: Registro {idx+1} no es un diccionario: {type(record)}")
                    raise ValueError(f"Registro {idx+1} no es un diccionario: {type(record)}")
                if not record:
                    logger.error(f"[FALLBACK] ERROR: Registro {idx+1} está vacío")
                    raise ValueError(f"Registro {idx+1} está vacío")
        
        # Crear registros
        logger.info(f"[FALLBACK] >>> Llamando a create() para {len(records_to_create)} registros de {model}...")
        try:
            created_ids = self.create(model, records_to_create)
            logger.info(f"[FALLBACK] <<< create() completado, {len(created_ids)} registros creados")
            
            # Registrar en migration.tracking
            tracking_data = []
            for created_id, v13_id in zip(created_ids, v13_ids_to_create):
                v13_id_str = str(v13_id)
                result['created'][v13_id_str] = created_id
                result['stats']['created'] += 1
                
                tracking_data.append({
                    'name': f"{model} - V13:{v13_id} -> V18:{created_id}",
                    'model_name': model,
                    'v13_id': v13_id,
                    'v18_id': created_id,
                    'batch_id': batch_id,
                    'status': 'created',
                })
            
            # Crear registros de tracking en batch
            if tracking_data:
                logger.info(f"[FALLBACK] Registrando {len(tracking_data)} registros en migration.tracking...")
                try:
                    tracking_ids = self.models.execute_kw(
                        self.db, self.uid, self.password,
                        'migration.tracking', 'create',
                        [tracking_data]
                    )
                    logger.info(f"[FALLBACK] ✓ Registrados {len(tracking_data)} registros en migration.tracking (IDs: {tracking_ids[:5] if len(tracking_ids) > 5 else tracking_ids}...)")
                except Exception as e:
                    logger.error(f"[FALLBACK] ✗ Error registrando en migration.tracking: {e}")
                    # Intentar crear uno por uno como fallback
                    logger.warning("[FALLBACK] Intentando registrar tracking uno por uno...")
                    for tracking_item in tracking_data:
                        try:
                            self.models.execute_kw(
                                self.db, self.uid, self.password,
                                'migration.tracking', 'create',
                                [[tracking_item]]
                            )
                        except Exception as e2:
                            logger.error(f"[FALLBACK] Error en tracking individual para v13_id={tracking_item.get('v13_id')}: {e2}")
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"[FALLBACK] Error creando registros: {error_msg}")
            
            # Guardar información detallada de cada registro que falló
            for idx, (record_data, v13_id) in enumerate(zip(records_to_create, v13_ids_to_create)):
                v13_id_str = str(v13_id)
                result['errors'][v13_id_str] = error_msg
                result['stats']['errors'] += 1
                
                # Log detallado del registro que falló
                logger.error(f"[ERROR DETALLADO] Registro fallido - Modelo: {model}, ID v13: {v13_id}")
                logger.error(f"[ERROR DETALLADO] Error: {error_msg}")
                
                # Guardar información del registro (limitado a campos clave para no saturar logs)
                key_fields = ['name', 'id', 'parent_id', 'category_id', 'email', 'vat']
                record_summary = {k: v for k, v in record_data.items() if k in key_fields}
                logger.error(f"[ERROR DETALLADO] Campos clave del registro: {json.dumps(record_summary, indent=2, ensure_ascii=False)}")
                
                # Nota: No se puede llamar a _log_failed_record aquí porque este método está en OdooConnection
                # y _log_failed_record está en MigrationScript. El error se manejará en el nivel superior.
        
        # Log final del resultado
        logger.info(f"[FALLBACK] ✓ Resultado para {model}: Creados={result['stats']['created']}, Omitidos={result['stats']['skipped']}, Errores={result['stats']['errors']}")
        
        return result
    
    def _verify_batch_completion(self, model: str, batch_id: str, v13_ids: List[int]) -> Dict:
        """
        Verifica en migration.tracking si un batch se completó correctamente.
        Se usa como alternativa cuando XML-RPC no retorna respuesta.
        
        Args:
            model: Nombre del modelo
            batch_id: ID del batch
            v13_ids: Lista de IDs v13 que se intentaron migrar
        
        Returns:
            Diccionario con estadísticas similar a migrate_batch, o None si no se puede verificar
        """
        try:
            logger.info(f"[VERIFICACIÓN] Buscando registros en migration.tracking con batch_id={batch_id}...")
            
            # Buscar registros en migration.tracking con este batch_id
            tracking_records = self.search_read(
                'migration.tracking',
                [['model_name', '=', model], ['batch_id', '=', batch_id]],
                ['v13_id', 'v18_id', 'status', 'error_message'],
                limit=10000
            )
            
            if not tracking_records:
                logger.warning(f"[VERIFICACIÓN] No se encontraron registros en migration.tracking con batch_id={batch_id}")
                return None
            
            logger.info(f"[VERIFICACIÓN] Encontrados {len(tracking_records)} registros en migration.tracking")
            
            # Contar por estado
            stats = {'created': 0, 'skipped': 0, 'errors': 0}
            v13_ids_found = set()
            
            for record in tracking_records:
                status = record.get('status', '')
                v13_id = record.get('v13_id')
                
                if v13_id:
                    v13_ids_found.add(v13_id)
                
                if status == 'created':
                    stats['created'] += 1
                elif status == 'skipped':
                    stats['skipped'] += 1
                elif status == 'error':
                    stats['errors'] += 1
            
            # Verificar si todos los v13_ids están en migration.tracking
            v13_ids_set = set(v13_ids)
            missing_ids = v13_ids_set - v13_ids_found
            
            if missing_ids:
                logger.warning(f"[VERIFICACIÓN] {len(missing_ids)} IDs v13 no encontrados en migration.tracking")
                # Asumir que los faltantes son errores
                stats['errors'] += len(missing_ids)
            
            logger.info(f"[VERIFICACIÓN] Estadísticas: Creados={stats['created']}, Omitidos={stats['skipped']}, Errores={stats['errors']}")
            
            return {
                'stats': stats,
                'success': True,
                'verified_from_tracking': True
            }
            
        except Exception as e:
            logger.error(f"[VERIFICACIÓN] Error verificando batch en migration.tracking: {e}")
            return None
    
    def get_migration_mapping(self, model_name: str) -> Dict[str, int]:
        """
        Obtiene el mapeo de IDs v13 -> v18 desde migration.tracking
        
        Args:
            model_name: Nombre del modelo
        
        Returns:
            Diccionario {v13_id_str: v18_id}
        """
        try:
            logger.debug(f"[GET_MAPPING] Obteniendo mapeo para {model_name} desde migration.tracking...")
            # Usar search_read directamente con la estructura correcta para v18
            tracking_records = self.search_read(
                'migration.tracking',
                [['model_name', '=', model_name], ['status', 'in', ['created', 'skipped']]],
                ['v13_id', 'v18_id', 'status'],
                limit=100000
            )
            
            logger.debug(f"[GET_MAPPING] Encontrados {len(tracking_records)} registros en migration.tracking para {model_name}")
            
            mapping = {}
            incomplete_count = 0
            for record in tracking_records:
                v13_id = record.get('v13_id')
                v18_id = record.get('v18_id')
                status = record.get('status', 'unknown')
                if v13_id is not None and v18_id is not None:
                    mapping[str(v13_id)] = v18_id
                else:
                    incomplete_count += 1
                    logger.warning(f"[GET_MAPPING] Registro con datos incompletos: v13_id={v13_id}, v18_id={v18_id}, status={status}")
            
            if incomplete_count > 0:
                logger.warning(f"[GET_MAPPING] {incomplete_count} registros con datos incompletos en migration.tracking para {model_name}")
            
            logger.info(f"[GET_MAPPING] ✓ Mapeo obtenido para {model_name}: {len(mapping)} registros mapeados")
            if len(mapping) > 0 and len(mapping) <= 10:
                # Mostrar todos los mapeos si son pocos
                logger.debug(f"[GET_MAPPING] Mapeos completos: {mapping}")
            elif len(mapping) > 10:
                # Mostrar solo los primeros 5 si son muchos
                sample = dict(list(mapping.items())[:5])
                logger.debug(f"[GET_MAPPING] Muestra de mapeos (primeros 5 de {len(mapping)}): {sample}...")
            
            return mapping
        except Exception as e:
            logger.error(f"[GET_MAPPING] ✗ Error obteniendo mapeo para {model_name}: {e}")
            import traceback
            logger.debug(f"[GET_MAPPING] Traceback: {traceback.format_exc()}")
            return {}
    
    def count_migration_tracking(self, model_name: str, domain: List = None) -> int:
        """
        Cuenta registros en migration.tracking para un modelo.
        
        Args:
            model_name: Nombre del modelo
            domain: Dominio adicional (opcional). Se combinará con el dominio base.
        
        Returns:
            Número de registros en migration.tracking
        """
        try:
            # Construir el dominio base
            base_domain = [['model_name', '=', model_name], ['status', 'in', ['created', 'skipped']]]
            
            # Si se proporciona un dominio adicional, combinarlo
            if domain:
                final_domain = ['&'] + base_domain + domain
            else:
                final_domain = base_domain
            
            return self.models.execute_kw(
                self.db, self.uid, self.password,
                'migration.tracking', 'search_count',
                [final_domain]
            )
        except Exception as e:
            logger.warning(f"⚠ No se pudo contar registros en migration.tracking para {model_name}: {e}")
            return 0


class MigrationScript:
    """Script principal de migración"""
    
    def __init__(self):
        self.v13_conn = None
        self.v18_conn = None
        self.output_dir = "imports"
        self.errors_dir = "errors"
        self.batch_size = 100
        self.test_mode = False
        self.field_mappings = self.load_field_mappings()
        self.m2m_fields_config = self.load_m2m_fields_config()
        self.m2o_fields_by_name = self.load_m2o_fields_by_name()
        self.model_name_mapping = self.load_model_name_mapping()
        
        # Cargar mapeos de currency, uom y uom.category
        self.currency_mapping = self.load_currency_mapping()
        self.uom_mapping = self.load_uom_mapping()
        self.uom_category_mapping = self.load_uom_category_mapping()
        self.subscription_template_mapping = self.load_subscription_template_mapping()
        self.pricelist_mapping = {}  # Se carga dinámicamente cuando se necesite
        self.oldv13_tag_id = None  # Se carga dinámicamente cuando se necesite
        
        # Crear directorio de errores
        os.makedirs(self.errors_dir, exist_ok=True)
    
    def _log_failed_record(self, model: str, v13_id: int, record_data: Dict, 
                          error_msg: str, batch_num: int = None, total_batches: int = None):
        """
        Guarda información detallada de un registro que falló en un archivo JSON.
        
        Args:
            model: Nombre del modelo
            v13_id: ID v13 del registro
            record_data: Datos del registro que falló
            error_msg: Mensaje de error
            batch_num: Número de batch (opcional)
            total_batches: Total de batches (opcional)
        """
        try:
            error_file = os.path.join(self.errors_dir, f"errors_{model.replace('.', '_')}.json")
            
            logger.debug(f"[ERROR LOG] Intentando guardar error para {model} v13_id={v13_id} en {error_file}")
            
            # Cargar errores existentes o crear nuevo
            if os.path.exists(error_file):
                try:
                    with open(error_file, 'r', encoding='utf-8') as f:
                        errors = json.load(f)
                    logger.debug(f"[ERROR LOG] Archivo de errores existente cargado: {len(errors.get('errors', []))} errores previos")
                except Exception as load_error:
                    logger.warning(f"[ERROR LOG] Error cargando archivo de errores existente: {load_error}, creando nuevo")
                    errors = {
                        'model': model,
                        'errors': []
                    }
            else:
                errors = {
                    'model': model,
                    'errors': []
                }
                logger.debug(f"[ERROR LOG] Creando nuevo archivo de errores: {error_file}")
            
            # Validar que record_data sea un diccionario
            if not isinstance(record_data, dict):
                logger.warning(f"[ERROR LOG] record_data no es un diccionario: {type(record_data)}, convirtiendo...")
                record_data = {'error': 'Datos no válidos', 'original_type': str(type(record_data)), 'original_data': str(record_data)}
            
            # Crear entrada de error
            error_entry = {
                'v13_id': v13_id,
                'error': str(error_msg),  # Asegurar que sea string
                'batch_info': {
                    'batch_num': batch_num,
                    'total_batches': total_batches
                } if batch_num else None,
                'timestamp': datetime.now().isoformat(),
                'record_data': record_data
            }
            
            errors['errors'].append(error_entry)
            logger.debug(f"[ERROR LOG] Entrada de error agregada. Total de errores: {len(errors['errors'])}")
            
            # Guardar archivo
            try:
                with open(error_file, 'w', encoding='utf-8') as f:
                    json.dump(errors, f, indent=2, ensure_ascii=False, default=str)
                logger.info(f"[ERROR LOG] ✓ Error guardado en {error_file} (Total: {len(errors['errors'])} errores)")
            except Exception as save_error:
                logger.error(f"[ERROR LOG] ✗ Error guardando archivo de errores: {save_error}")
                import traceback
                logger.error(f"[ERROR LOG] Traceback: {traceback.format_exc()}")
                raise
        except Exception as e:
            logger.error(f"[ERROR LOG] ✗✗✗ Error crítico en _log_failed_record: {e}")
            logger.error(f"[ERROR LOG] Modelo: {model}, v13_id: {v13_id}, tipo v13_id: {type(v13_id)}")
            logger.error(f"[ERROR LOG] record_data tipo: {type(record_data)}")
            import traceback
            logger.error(f"[ERROR LOG] Traceback completo: {traceback.format_exc()}")
            # No re-lanzar el error para no interrumpir el proceso de migración
        
    def load_field_mappings(self) -> Dict[str, Dict[str, Dict[str, str]]]:
        """
        Carga mapeos de campos desde exceptions/field_mappings.json
        
        Returns:
            Diccionario con mapeos de campos por modelo
        """
        mappings_file = os.path.join('exceptions', 'field_mappings.json')
        
        if not os.path.exists(mappings_file):
            logger.debug(f"Archivo de mapeos no encontrado: {mappings_file}")
            return {}
        
        try:
            with open(mappings_file, 'r', encoding='utf-8') as f:
                mappings = json.load(f)
            logger.info(f"✓ Mapeos de campos cargados desde {mappings_file}")
            return mappings
        except Exception as e:
            logger.warning(f"⚠ No se pudieron cargar mapeos de campos desde {mappings_file}: {e}")
            return {}
    
    def load_m2m_fields_config(self) -> Dict[str, List[str]]:
        """
        Carga configuración de campos many2many permitidos desde exceptions/m2m_fields.json
        
        Returns:
            Diccionario con lista de campos many2many permitidos por modelo
        """
        config_file = os.path.join('exceptions', 'm2m_fields.json')
        
        if not os.path.exists(config_file):
            logger.debug(f"Archivo de configuración m2m_fields no encontrado: {config_file}")
            return {}
        
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Convertir el formato del JSON a una lista simple de campos permitidos
            m2m_config = {}
            for model, fields_dict in config.items():
                # fields_dict es un diccionario donde las claves son los nombres de los campos
                m2m_config[model] = list(fields_dict.keys())
            
            logger.info(f"✓ Configuración de campos many2many cargada desde {config_file}")
            logger.debug(f"  Campos many2many permitidos: {m2m_config}")
            return m2m_config
        except Exception as e:
            logger.warning(f"⚠ Error cargando configuración de campos many2many: {e}")
            return {}
    
    def load_m2o_fields_by_name(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """
        Carga configuración de campos many2one que deben buscarse/crearse por nombre.
        
        Returns:
            Diccionario con configuración de campos many2one por modelo
        """
        config_file = os.path.join('exceptions', 'm2o_fields_by_name.json')
        
        if not os.path.exists(config_file):
            logger.debug(f"Archivo de configuración m2o_fields_by_name no encontrado: {config_file}")
            return {}
        
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            logger.info(f"✓ Configuración de campos many2one por nombre cargada desde {config_file}")
            logger.debug(f"  Campos many2one por nombre: {config}")
            return config
        except Exception as e:
            logger.warning(f"⚠ Error cargando configuración de campos many2one por nombre: {e}")
            return {}
    
    def load_model_name_mapping(self) -> Dict[str, Dict[str, str]]:
        """
        Carga el mapeo de nombres de modelos entre v13 y v18.
        
        Returns:
            Diccionario con el mapeo de nombres de modelos
        """
        mapping_file = os.path.join('exceptions', 'model_name_mapping.json')
        try:
            if os.path.exists(mapping_file):
                with open(mapping_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Retornar ambos mapeos para facilitar el uso
                    return {
                        'v13_to_v18': data.get('v13_to_v18', {}),
                        'v18_to_v13': data.get('v18_to_v13', {})
                    }
            else:
                logger.debug(f"No se encontró archivo de mapeo de nombres de modelos: {mapping_file}")
                return {'v13_to_v18': {}, 'v18_to_v13': {}}
        except Exception as e:
            logger.warning(f"⚠ Error cargando mapeo de nombres de modelos: {e}")
            return {'v13_to_v18': {}, 'v18_to_v13': {}}
    
    def load_currency_mapping(self) -> Dict[str, int]:
        """
        Carga el mapeo de monedas desde currency_mapping.json
        
        Returns:
            Diccionario {v13_id_str: v18_id}
        """
        mapping_file = 'currency_mapping.json'
        try:
            if os.path.exists(mapping_file):
                with open(mapping_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    mapping = data.get('mapping', {})
                    logger.info(f"✓ Mapeo de monedas cargado: {len(mapping)} mapeos")
                    return mapping
            else:
                logger.debug(f"No se encontró archivo de mapeo de monedas: {mapping_file}")
                return {}
        except Exception as e:
            logger.warning(f"⚠ Error cargando mapeo de monedas: {e}")
            return {}
    
    def load_uom_mapping(self) -> Dict[str, Dict]:
        """
        Carga el mapeo de unidades de medida desde uom_mapping.json
        
        Returns:
            Diccionario con 'mapping' {v13_id_str: v18_id} y 'name_changes' para registrar cambios
        """
        mapping_file = 'uom_mapping.json'
        try:
            if os.path.exists(mapping_file):
                with open(mapping_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    mapping = data.get('mapping', {})
                    # Identificar cambios de nombre
                    name_changes = {}
                    for match in data.get('matches_by_id', []):
                        v13_id = str(match.get('id'))
                        v13_name = match.get('v13_name', '')
                        v18_name = match.get('v18_name', '')
                        if v13_name != v18_name and v13_name and v18_name:
                            name_changes[v13_id] = {
                                'v13_name': v13_name,
                                'v18_name': v18_name,
                                'v18_id': match.get('id')  # Si coincide por ID, el ID es el mismo
                            }
                    
                    logger.info(f"✓ Mapeo de unidades de medida cargado: {len(mapping)} mapeos, {len(name_changes)} cambios de nombre")
                    return {
                        'mapping': mapping,
                        'name_changes': name_changes
                    }
            else:
                logger.debug(f"No se encontró archivo de mapeo de unidades: {mapping_file}")
                return {'mapping': {}, 'name_changes': {}}
        except Exception as e:
            logger.warning(f"⚠ Error cargando mapeo de unidades de medida: {e}")
            return {'mapping': {}, 'name_changes': {}}
    
    def load_uom_category_mapping(self) -> Dict[str, int]:
        """
        Carga el mapeo de categorías de unidades de medida desde uom_category_mapping.json
        
        Returns:
            Diccionario {v13_id_str: v18_id}
        """
        mapping_file = 'uom_category_mapping.json'
        try:
            if os.path.exists(mapping_file):
                with open(mapping_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    mapping = data.get('mapping', {})
                    logger.info(f"✓ Mapeo de categorías UoM cargado: {len(mapping)} mapeos")
                    return mapping
            else:
                logger.debug(f"No se encontró archivo de mapeo de categorías UoM: {mapping_file}")
                return {}
        except Exception as e:
            logger.warning(f"⚠ Error cargando mapeo de categorías UoM: {e}")
            return {}
    
    def load_subscription_template_mapping(self) -> Dict[str, int]:
        """
        Carga el mapeo de templates de suscripción.
        El mapeo se usa para determinar qué template_id asignar basándose en 
        recurring_rule_type y recurring_interval del contrato v13.
        
        Returns:
            Diccionario {key: template_id} donde key = "{recurring_rule_type}_{recurring_interval}"
        """
        # Mapeo directo basado en los templates creados
        # Template ID 1: Mensual (monthly, interval=1) - 863 contratos
        # Template ID 2: Anual intervalo 1 (yearly, interval=1) - 134 contratos
        # Template ID 3: Anual intervalo 2 (yearly, interval=2) - 1 contrato
        # Template ID 4: Anual intervalo 3 (yearly, interval=3) - 1 contrato
        # Template ID 5: Anual intervalo 5 (yearly, interval=5) - 1 contrato
        
        mapping = {
            'monthly_1': 1,  # Template ID 1
            'yearly_1': 2,   # Template ID 2
            'yearly_2': 3,   # Template ID 3
            'yearly_3': 4,   # Template ID 4
            'yearly_5': 5,   # Template ID 5
        }
        
        # Intentar cargar desde archivo si existe
        mapping_file = 'subscription_template_mapping.json'
        try:
            if os.path.exists(mapping_file):
                with open(mapping_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # El archivo puede tener formato simple (solo números) o formato completo (diccionarios)
                    for key, template_data in data.items():
                        if isinstance(template_data, dict) and 'template_id' in template_data:
                            # Formato completo: {'monthly_1': {'template_id': 1, ...}}
                            mapping[key] = template_data['template_id']
                        elif isinstance(template_data, int):
                            # Formato simple: {'monthly_1': 1}
                            mapping[key] = template_data
                    
                    # Actualizar el mapeo por defecto con los valores del archivo
                    mapping.update({k: v for k, v in mapping.items()})
                    
                    logger.info(f"✓ Mapeo de templates de suscripción cargado: {len(mapping)} templates")
                    return mapping
        except Exception as e:
            logger.warning(f"⚠ Error cargando mapeo de templates de suscripción: {e}")
        
        logger.info(f"✓ Mapeo de templates de suscripción (por defecto): {len(mapping)} templates")
        return mapping
    
    def get_template_id_for_contract(self, recurring_rule_type: str, recurring_interval: int) -> int:
        """
        Obtiene el template_id para un contrato basándose en sus campos de recurrencia.
        
        Args:
            recurring_rule_type: Tipo de recurrencia ('monthly', 'yearly', etc.)
            recurring_interval: Intervalo de recurrencia (1, 2, 3, 5, etc.)
        
        Returns:
            template_id (int) o 1 si no se encuentra (template mensual por defecto)
        """
        if not recurring_rule_type or not recurring_interval:
            # Usar template mensual por defecto
            return self.subscription_template_mapping.get('monthly_1', 1)
        
        key = f"{recurring_rule_type.lower()}_{recurring_interval}"
        template_id = self.subscription_template_mapping.get(key)
        
        if template_id:
            logger.debug(f"[TEMPLATE] Template encontrado para {key}: ID={template_id}")
            return template_id
        else:
            # Usar template mensual por defecto si no se encuentra
            logger.warning(f"⚠ Template no encontrado para {key}, usando template mensual por defecto")
            return self.subscription_template_mapping.get('monthly_1', 1)
    
    def ensure_subscription_templates(self) -> bool:
        """
        Verifica que existan las plantillas de suscripción necesarias en v18.
        Si no existen, las crea automáticamente.
        
        Returns:
            True si las plantillas existen o se crearon exitosamente, False en caso contrario
        """
        try:
            logger.info("[VERIFICACIÓN] Verificando plantillas de suscripción en v18...")
            
            # Verificar si existen plantillas
            existing_templates = self.v18_conn.search_read(
                'sale.subscription.template', 
                [], 
                ['id', 'name', 'code', 'recurring_rule_type', 'recurring_interval']
            )
            
            if existing_templates:
                logger.info(f"[VERIFICACIÓN] ✓ Encontradas {len(existing_templates)} plantillas de suscripción existentes")
                # Actualizar el mapeo con las plantillas existentes
                for template in existing_templates:
                    rule_type = template.get('recurring_rule_type', 'monthly')
                    interval = template.get('recurring_interval', 1)
                    key = f"{rule_type.lower()}_{interval}"
                    self.subscription_template_mapping[key] = template['id']
                return True
            
            # Si no existen, crearlas
            logger.warning("[VERIFICACIÓN] ⚠ No se encontraron plantillas de suscripción, creándolas...")
            
            templates_to_create = [
                {
                    'name': 'Template Mensual Pre-pago (Migración v13)',
                    'description': 'Template para contratos mensuales con pago anticipado migrados desde v13',
                    'recurring_rule_type': 'monthly',
                    'recurring_interval': 1,
                    'recurring_rule_boundary': False,
                    'recurring_rule_count': 0,
                    'code': 'TEMPLATE_MONTHLY_V13'
                },
                {
                    'name': 'Template Anual Pre-pago Intervalo 1 (Migración v13)',
                    'description': 'Template para contratos anuales con pago anticipado migrados desde v13',
                    'recurring_rule_type': 'yearly',
                    'recurring_interval': 1,
                    'recurring_rule_boundary': False,
                    'recurring_rule_count': 0,
                    'code': 'TEMPLATE_YEARLY_1_V13'
                },
                {
                    'name': 'Template Anual Pre-pago Intervalo 2 (Migración v13)',
                    'description': 'Template para contratos anuales cada 2 años migrados desde v13',
                    'recurring_rule_type': 'yearly',
                    'recurring_interval': 2,
                    'recurring_rule_boundary': False,
                    'recurring_rule_count': 0,
                    'code': 'TEMPLATE_YEARLY_2_V13'
                },
                {
                    'name': 'Template Anual Pre-pago Intervalo 3 (Migración v13)',
                    'description': 'Template para contratos anuales cada 3 años migrados desde v13',
                    'recurring_rule_type': 'yearly',
                    'recurring_interval': 3,
                    'recurring_rule_boundary': False,
                    'recurring_rule_count': 0,
                    'code': 'TEMPLATE_YEARLY_3_V13'
                },
                {
                    'name': 'Template Anual Pre-pago Intervalo 5 (Migración v13)',
                    'description': 'Template para contratos anuales cada 5 años migrados desde v13',
                    'recurring_rule_type': 'yearly',
                    'recurring_interval': 5,
                    'recurring_rule_boundary': False,
                    'recurring_rule_count': 0,
                    'code': 'TEMPLATE_YEARLY_5_V13'
                }
            ]
            
            created_count = 0
            for template_data in templates_to_create:
                code = template_data['code']
                
                # Verificar si ya existe
                existing = self.v18_conn.search_read(
                    'sale.subscription.template', 
                    [['code', '=', code]], 
                    ['id']
                )
                
                if existing:
                    template_id = existing[0]['id']
                    logger.info(f"[VERIFICACIÓN] ✓ Template '{template_data['name']}' ya existe (ID={template_id})")
                else:
                    try:
                        template_ids = self.v18_conn.create('sale.subscription.template', [template_data])
                        if template_ids and len(template_ids) > 0:
                            template_id = template_ids[0]
                            logger.info(f"[VERIFICACIÓN] ✓ Template '{template_data['name']}' creado (ID={template_id})")
                            created_count += 1
                        else:
                            logger.error(f"[VERIFICACIÓN] ✗ Error creando template '{template_data['name']}': No se retornó ID")
                            continue
                    except Exception as e:
                        logger.error(f"[VERIFICACIÓN] ✗ Error creando template '{template_data['name']}': {e}")
                        continue
                
                # Actualizar mapeo
                key = f"{template_data['recurring_rule_type'].lower()}_{template_data['recurring_interval']}"
                self.subscription_template_mapping[key] = template_id
            
            if created_count > 0:
                logger.info(f"[VERIFICACIÓN] ✓ {created_count} plantillas creadas exitosamente")
            
            # Verificar que al menos una plantilla existe
            final_templates = self.v18_conn.search_read(
                'sale.subscription.template', 
                [], 
                ['id']
            )
            
            if final_templates:
                logger.info(f"[VERIFICACIÓN] ✓ Verificación completada: {len(final_templates)} plantillas disponibles")
                return True
            else:
                logger.error("[VERIFICACIÓN] ✗ ERROR CRÍTICO: No se pudieron crear plantillas de suscripción")
                return False
                
        except Exception as e:
            logger.error(f"[VERIFICACIÓN] ✗ Error verificando/creando plantillas de suscripción: {e}")
            import traceback
            logger.debug(f"[VERIFICACIÓN] Traceback: {traceback.format_exc()}")
            return False
    
    def get_v13_model_name(self, v18_model: str) -> str:
        """
        Obtiene el nombre del modelo en v13 a partir del nombre en v18.
        Si no hay mapeo, retorna el mismo nombre.
        
        Args:
            v18_model: Nombre del modelo en v18
        
        Returns:
            Nombre del modelo en v13
        """
        if not hasattr(self, 'model_name_mapping'):
            return v18_model
        
        v18_to_v13 = self.model_name_mapping.get('v18_to_v13', {})
        if v18_model in v18_to_v13:
            v13_name = v18_to_v13[v18_model].get('v13_name', v18_model)
            logger.info(f"[MAPEO MODELO] {v18_model} (v18) -> {v13_name} (v13)")
            return v13_name
        
        return v18_model
    
    def get_v18_model_name(self, v13_model: str) -> str:
        """
        Obtiene el nombre del modelo en v18 a partir del nombre en v13.
        Si no hay mapeo, retorna el mismo nombre.
        
        Args:
            v13_model: Nombre del modelo en v13
        
        Returns:
            Nombre del modelo en v18
        """
        if not hasattr(self, 'model_name_mapping'):
            return v13_model
        
        v13_to_v18 = self.model_name_mapping.get('v13_to_v18', {})
        if v13_model in v13_to_v18:
            v18_name = v13_to_v18[v13_model].get('v18_name', v13_model)
            logger.info(f"[MAPEO MODELO] {v13_model} (v13) -> {v18_name} (v18)")
            return v18_name
        
        return v13_model
    
    def get_or_create_oldv13_tag(self) -> int:
        """
        Obtiene o crea la etiqueta "OLDv13" en product.tag.
        
        Returns:
            ID de la etiqueta "OLDv13"
        """
        try:
            # Buscar si ya existe la etiqueta "OLDv13"
            existing_tags = self.v18_conn.search_read(
                'product.tag',
                [['name', '=', 'OLDv13']],
                ['id', 'name']
            )
            
            if existing_tags:
                tag_id = existing_tags[0]['id']
                logger.debug(f"[ETIQUETA] Etiqueta 'OLDv13' ya existe (ID: {tag_id})")
                return tag_id
            
            # Si no existe, crearla
            logger.info("[ETIQUETA] Creando etiqueta 'OLDv13' en product.tag...")
            tag_ids = self.v18_conn.create('product.tag', [{'name': 'OLDv13'}])
            
            if tag_ids and len(tag_ids) > 0:
                tag_id = tag_ids[0]
                logger.info(f"[ETIQUETA] ✓ Etiqueta 'OLDv13' creada (ID: {tag_id})")
                return tag_id
            else:
                logger.error("[ETIQUETA] ✗ Error: No se retornó ID al crear etiqueta 'OLDv13'")
                return False
                
        except Exception as e:
            logger.error(f"[ETIQUETA] ✗ Error obteniendo/creando etiqueta 'OLDv13': {e}")
            import traceback
            logger.debug(f"[ETIQUETA] Traceback: {traceback.format_exc()}")
            return False
    
    def load_env_file(self, env_file: str = '.env'):
        """Carga variables de entorno desde un archivo .env"""
        if not os.path.exists(env_file):
            logger.debug(f"Archivo {env_file} no encontrado, usando variables de entorno del sistema")
            return
        
        logger.info(f"Cargando variables de entorno desde {env_file}...")
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    os.environ[key] = value
    
    def load_env(self):
        """Carga variables de entorno"""
        logger.info("Cargando configuración desde variables de entorno...")
        
        # Intentar cargar archivo .env si existe
        self.load_env_file('.env')
        
        # Configuración V13 (solo lectura)
        v13_url = os.getenv('V13_URL', 'http://localhost:8069')
        v13_db = os.getenv('V13_DB', 'odoo13')
        v13_username = os.getenv('V13_USERNAME', 'admin')
        v13_password = os.getenv('V13_PASSWORD', 'admin')
        
        # Configuración V18
        v18_url = os.getenv('V18_URL', 'http://localhost:8069')
        v18_db = os.getenv('V18_DB', 'odoo18')
        v18_username = os.getenv('V18_USERNAME', 'admin')
        v18_password = os.getenv('V18_PASSWORD', 'admin')
        
        # Batch size
        batch_size = int(os.getenv('BATCH_SIZE', '100'))
        if batch_size < 100:
            logger.warning("⚠ Batch size menor a 100, usando 100")
            batch_size = 100
        self.batch_size = batch_size
        
        # Modo test
        test_mode = os.getenv('TEST_MODE', 'False').lower() in ('true', '1', 'yes', 'si', 'sí')
        self.test_mode = test_mode
        
        # Crear conexiones
        self.v13_conn = OdooConnection(v13_url, v13_db, v13_username, v13_password)
        if not test_mode:
            self.v18_conn = OdooConnection(v18_url, v18_db, v18_username, v18_password)
        else:
            logger.warning("⚠ MODO TEST ACTIVADO - No se crearán registros en v18")
            # En modo test, crear conexión pero no usarla para crear
            self.v18_conn = OdooConnection(v18_url, v18_db, v18_username, v18_password)
        
        # Crear directorio de salida
        os.makedirs(self.output_dir, exist_ok=True)
        
        mode_text = "TEST" if test_mode else "PRODUCCIÓN"
        logger.info(f"✓ Configuración cargada (Batch size: {self.batch_size}, Modo: {mode_text})")
    
    def get_stored_fields(self, model: str, conn: OdooConnection, 
                         allow_many2one: bool = False, 
                         models_list: List[str] = None,
                         v18_model_name: str = None) -> List[str]:
        """
        Obtiene lista de campos almacenados de un modelo.
        
        Args:
            model: Nombre del modelo en v13 (puede ser diferente al de v18)
            conn: Conexión Odoo
            allow_many2one: Si True, incluye campos many2one especificados
            models_list: Lista de modelos a migrar (para filtrar many2one)
            v18_model_name: Nombre del modelo en v18 (opcional, para verificaciones especiales)
        
        Returns:
            Lista de nombres de campos almacenados
        """
        # Si no se proporciona v18_model_name, usar el mismo nombre del modelo
        # Esto es para compatibilidad con llamadas existentes
        if v18_model_name is None:
            v18_model_name = model
        
        # Caso especial: Para sale.subscription.line, siempre incluir contract_id aunque no exista en v13
        # Esto es necesario para poder mapear las líneas a sus suscripciones
        force_include_contract_id = (v18_model_name == 'sale.subscription.line' or model == 'contract.line')
        
        try:
            fields_info = conn.get_fields(model)
            stored_fields = []
            
            # Si force_include_contract_id es True y contract_id no está en fields_info, agregarlo manualmente
            if force_include_contract_id and 'contract_id' not in fields_info:
                logger.info(f"  ⚠ Campo 'contract_id' no encontrado en {model} (v13), pero se incluirá para mapeo a sale_subscription_id")
                # Agregar contract_id como campo many2one ficticio para que se incluya en la exportación
                fields_info['contract_id'] = {
                    'type': 'many2one',
                    'relation': 'contract.contract',
                    'store': True,
                    'required': False
                }
            
            for field_name, field_info in fields_info.items():
                field_type = field_info.get('type', '')
                
                # Excluir campos one2many (nunca se incluyen)
                if field_type == 'one2many':
                    continue
                
                # Incluir campos many2many (se exportan para reconstruir relaciones)
                if field_type == 'many2many':
                    # Verificar que el modelo relacionado esté en la lista de modelos a migrar
                    relation = field_info.get('relation', '')
                    if models_list and relation not in models_list:
                        logger.debug(f"  Excluyendo campo many2many '{field_name}' -> '{relation}' (no está en models_to_migrate.txt)")
                        continue
                    # Incluir el campo many2many
                    stored_fields.append(field_name)
                    continue
                
                # Many2one solo si está permitido Y el modelo relacionado está en models_list
                # EXCEPCIÓN: parent_id siempre se incluye si el modelo está en models_list (apunta al mismo modelo)
                # EXCEPCIÓN: uom_id y uom_po_id siempre se incluyen en product.template y product.product (requeridos en v18)
                if field_type == 'many2one':
                    # parent_id es especial: siempre se incluye si el modelo está en models_list
                    if field_name == 'parent_id':
                        if models_list and model in models_list:
                            stored_fields.append(field_name)
                            logger.debug("  Incluyendo campo especial 'parent_id' (apunta al mismo modelo)")
                            continue
                        else:
                            logger.debug(f"  Excluyendo 'parent_id' (modelo {model} no está en models_to_migrate.txt)")
                            continue
                    
                    
                    # Campos especiales para sale.subscription: siempre se incluyen aunque los modelos relacionados no estén en la lista
                    # Estos campos son requeridos en v18 y pueden haber sido migrados en ejecuciones anteriores
                    # NOTA: model puede ser 'contract.contract' (v13) pero v18_model_name será 'sale.subscription' (v18)
                    if v18_model_name == 'sale.subscription' or model == 'contract.contract':
                        if field_name == 'partner_id':
                            stored_fields.append(field_name)
                            logger.debug(f"  Incluyendo campo especial 'partner_id' en {model} -> {v18_model_name} (requerido en v18, necesita mapeo desde v13)")
                            continue
                        if field_name == 'company_id':
                            stored_fields.append(field_name)
                            logger.debug(f"  Incluyendo campo especial 'company_id' en {model} -> {v18_model_name} (requerido en v18, necesita mapeo desde v13)")
                            continue
                        if field_name == 'pricelist_id':
                            stored_fields.append(field_name)
                            logger.debug(f"  Incluyendo campo especial 'pricelist_id' en {model} -> {v18_model_name} (requerido en v18, necesita mapeo desde v13)")
                            continue
                    
                    # contract_id es especial en contract.line: se necesita para mapear a sale_subscription_id en sale.subscription.line
                    # NOTA: model puede ser 'contract.line' (v13) pero v18_model_name será 'sale.subscription.line' (v18)
                    # IMPORTANTE: Siempre incluir contract_id si estamos exportando sale.subscription.line, incluso si el campo no existe en v13
                    if v18_model_name == 'sale.subscription.line' or model == 'contract.line':
                        if field_name == 'contract_id':
                            stored_fields.append(field_name)
                            logger.info(f"  ✓ Incluyendo campo especial 'contract_id' en {model} -> {v18_model_name} (se mapea a sale_subscription_id en sale.subscription.line)")
                            continue
                    
                    # recurring_rule_type y recurring_interval son especiales para contract.contract
                    # Se necesitan para determinar template_id en sale.subscription
                    if field_name in ['recurring_rule_type', 'recurring_interval'] and (v18_model_name == 'sale.subscription' or model == 'contract.contract'):
                        stored_fields.append(field_name)
                        logger.debug(f"  Incluyendo campo especial '{field_name}' en {model} -> {v18_model_name} (necesario para determinar template_id en sale.subscription)")
                        continue
                    
                    # quantity es especial en contract.line: se mapea a product_uom_qty en sale.subscription.line
                    if field_name == 'quantity' and (v18_model_name == 'sale.subscription.line' or model == 'contract.line'):
                        stored_fields.append(field_name)
                        logger.debug(f"  Incluyendo campo especial '{field_name}' en {model} -> {v18_model_name} (se mapea a product_uom_qty en sale.subscription.line)")
                        continue
                    
                    # specific_price es especial en contract.line: se mapea a price_unit en sale.subscription.line
                    if field_name == 'specific_price' and (v18_model_name == 'sale.subscription.line' or model == 'contract.line'):
                        stored_fields.append(field_name)
                        logger.debug(f"  Incluyendo campo especial '{field_name}' en {model} -> {v18_model_name} (se mapea a price_unit en sale.subscription.line)")
                        continue
                    
                    # IMPORTANTE: res.partner solo incluye campos many2one explícitos (state_id, country_id, parent_id)
                    # NO incluir otros campos many2one aunque allow_many2one=True
                    if model == 'res.partner':
                        # Solo incluir state_id, country_id y parent_id
                        if field_name in ['state_id', 'country_id']:
                            stored_fields.append(field_name)
                            logger.debug(f"  Incluyendo campo many2one '{field_name}' en {model} (búsqueda/creación por nombre configurada)")
                            continue
                        elif field_name == 'parent_id':
                            # parent_id se maneja por separado más abajo
                            pass
                        else:
                            # Excluir TODOS los demás campos many2one en res.partner
                            logger.debug(f"  Excluyendo campo many2one '{field_name}' en {model} (no está en la lista de campos permitidos)")
                            continue
                    
                    # Campos many2one que se buscan/crean por nombre (configurados en m2o_fields_by_name.json)
                    # crm.lead: lost_reason_id
                    if model == 'crm.lead' and field_name == 'lost_reason_id':
                        stored_fields.append(field_name)
                        logger.debug(f"  Incluyendo campo many2one '{field_name}' en {model} (búsqueda/creación por nombre configurada)")
                        continue
                    
                    # crm.stage: team_id
                    if model == 'crm.stage' and field_name == 'team_id':
                        stored_fields.append(field_name)
                        logger.debug(f"  Incluyendo campo many2one '{field_name}' en {model} (búsqueda/creación por nombre configurada)")
                        continue
                    
                    # Para otros campos many2one, aplicar las reglas normales
                    if not allow_many2one:
                        continue
                    
                    # Verificar que el modelo relacionado esté en la lista de modelos a migrar
                    relation = field_info.get('relation', '')
                    if models_list and relation not in models_list:
                        logger.info(f"  ⚠ Excluyendo campo many2one '{field_name}' -> '{relation}' (no está en models_to_migrate.txt)")
                        continue
                
                # Excluir campos computed que no tienen store=True
                # En Odoo, los campos computed tienen store=False
                # EXCEPCIÓN: 'name' en res.users siempre se incluye aunque sea computed
                # porque es necesario para crear el usuario correctamente
                store = field_info.get('store', True)
                if store is False:
                    # Excepción para 'name' en res.users
                    if field_name == 'name' and model == 'res.users':
                        stored_fields.append(field_name)
                        logger.debug("  Incluyendo campo especial 'name' en res.users (aunque sea computed)")
                        continue
                    else:
                        continue
                
                # Excluir campos de imagen para product.product (causan problemas con XML-RPC por tamaño)
                # Estos campos se pueden migrar después si es necesario
                if model == 'product.product' and field_name.startswith('image_'):
                    logger.debug(f"  Excluyendo campo de imagen '{field_name}' en {model} (causa problemas con XML-RPC)")
                    continue
                
                # Incluir el campo
                stored_fields.append(field_name)
            
            # Asegurar que siempre incluimos 'id' para el tracking
            if 'id' not in stored_fields:
                stored_fields.insert(0, 'id')
            
            return stored_fields
        except Exception as e:
            logger.warning(f"⚠ No se pudieron obtener campos de {model}, usando campos básicos: {e}")
            return ['id', 'name']
    
    def get_many2one_dependencies(self, model: str, conn: OdooConnection, 
                                  models_list: List[str]) -> List[str]:
        """
        Obtiene las dependencias many2one de un modelo.
        Retorna lista de modelos relacionados que están en models_list.
        
        Args:
            model: Nombre del modelo
            conn: Conexión Odoo
            models_list: Lista de modelos a migrar
        
        Returns:
            Lista de modelos de los que depende este modelo
        """
        dependencies = []
        try:
            # Agregar timeout para evitar que se quede pegado
            import signal
            
            def timeout_handler(signum, frame):
                raise TimeoutError(f"Timeout obteniendo campos de {model}")
            
            # Solo aplicar timeout en Linux/Unix
            if hasattr(signal, 'SIGALRM'):
                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(10)  # 10 segundos de timeout
            
            try:
                fields_info = conn.get_fields(model)
            finally:
                if hasattr(signal, 'SIGALRM'):
                    signal.alarm(0)  # Cancelar timeout
            
            for field_name, field_info in fields_info.items():
                field_type = field_info.get('type', '')
                
                if field_type == 'many2one':
                    relation = field_info.get('relation', '')
                    # Solo incluir si el modelo relacionado está en la lista de modelos a migrar
                    if relation and relation in models_list:
                        if relation not in dependencies:
                            dependencies.append(relation)
            
            return dependencies
        except (TimeoutError, Exception) as e:
            logger.warning(f"⚠ No se pudieron obtener dependencias de {model}: {e}")
            return []
    
    def sort_models_by_dependencies(self, models_config: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Ordena los modelos por dependencias usando topological sort.
        Los modelos sin dependencias se migran primero.
        
        Args:
            models_config: Lista de configuraciones de modelos
        
        Returns:
            Lista ordenada de modelos
        """
        model_names = [m['model'] for m in models_config]
        model_config_map = {m['model']: m for m in models_config}
        
        # Construir grafo de dependencias
        dependencies = {}
        for model_config in models_config:
            model = model_config['model']
            allow_many2one = model_config.get('allow_many2one', False)
            
            # Inicializar lista de dependencias
            dependencies[model] = []
            
            if allow_many2one:
                try:
                    deps = self.get_many2one_dependencies(model, self.v13_conn, model_names)
                    dependencies[model].extend(deps)
                except Exception as e:
                    logger.warning(f"⚠ Error obteniendo dependencias para {model}: {e}, continuando sin dependencias")
            
            # DEPENDENCIAS EXPLÍCITAS: Agregar dependencias conocidas aunque no estén en many2one
            # uom.uom depende de uom.category (category_id es requerido)
            if model == 'uom.uom' and 'uom.category' in model_names:
                if 'uom.category' not in dependencies[model]:
                    dependencies[model].append('uom.category')
                    logger.debug(f"[DEPENDENCIAS] Agregada dependencia explícita: {model} -> uom.category")
            
            # product.template depende de product.category y uom.uom (uom_id es requerido)
            # IMPORTANTE: product.template NO debe depender de product.product (es al revés)
            if model == 'product.template':
                # Limpiar dependencias incorrectas detectadas automáticamente
                if 'product.product' in dependencies[model]:
                    dependencies[model].remove('product.product')
                    logger.debug(f"[DEPENDENCIAS] Removida dependencia incorrecta product.product de {model}")
                # Agregar dependencias explícitas correctas
                if 'product.category' in model_names and 'product.category' not in dependencies[model]:
                    dependencies[model].append('product.category')
                if 'uom.uom' in model_names and 'uom.uom' not in dependencies[model]:
                    dependencies[model].append('uom.uom')
                logger.debug(f"[DEPENDENCIAS] Dependencias explícitas para {model}: {dependencies[model]}")
            
            # product.product depende de product.template (product_tmpl_id es requerido)
            # IMPORTANTE: product.product SIEMPRE debe migrarse DESPUÉS de product.template
            if model == 'product.product':
                # Limpiar dependencias circulares incorrectas
                if 'product.product' in dependencies[model]:
                    dependencies[model].remove('product.product')
                    logger.debug(f"[DEPENDENCIAS] Removida dependencia circular product.product de {model}")
                # Agregar dependencia explícita correcta
                if 'product.template' in model_names and 'product.template' not in dependencies[model]:
                    dependencies[model].append('product.template')
                logger.debug(f"[DEPENDENCIAS] Dependencias explícitas para {model}: {dependencies[model]}")
            
            # product.pricelist depende de res.currency (currency_id es requerido)
            if model == 'product.pricelist':
                if 'res.currency' in model_names and 'res.currency' not in dependencies[model]:
                    dependencies[model].append('res.currency')
                logger.debug(f"[DEPENDENCIAS] Dependencias explícitas para {model}: {dependencies[model]}")
            
            # product.pricelist.item depende de product.pricelist, product.template, product.product, product.category
            if model == 'product.pricelist.item':
                if 'product.pricelist' in model_names and 'product.pricelist' not in dependencies[model]:
                    dependencies[model].append('product.pricelist')
                if 'product.template' in model_names and 'product.template' not in dependencies[model]:
                    dependencies[model].append('product.template')
                if 'product.product' in model_names and 'product.product' not in dependencies[model]:
                    dependencies[model].append('product.product')
                if 'product.category' in model_names and 'product.category' not in dependencies[model]:
                    dependencies[model].append('product.category')
                logger.debug(f"[DEPENDENCIAS] Dependencias explícitas para {model}: {dependencies[model]}")
            
            # sale.subscription depende de res.partner, product.pricelist (template_id se crea antes)
            if model == 'sale.subscription':
                if 'res.partner' in model_names and 'res.partner' not in dependencies[model]:
                    dependencies[model].append('res.partner')
                if 'product.pricelist' in model_names and 'product.pricelist' not in dependencies[model]:
                    dependencies[model].append('product.pricelist')
                logger.debug(f"[DEPENDENCIAS] Dependencias explícitas para {model}: {dependencies[model]}")
            
            # sale.subscription.line depende de sale.subscription y product.product
            if model == 'sale.subscription.line':
                if 'sale.subscription' in model_names and 'sale.subscription' not in dependencies[model]:
                    dependencies[model].append('sale.subscription')
                if 'product.product' in model_names and 'product.product' not in dependencies[model]:
                    dependencies[model].append('product.product')
                logger.debug(f"[DEPENDENCIAS] Dependencias explícitas para {model}: {dependencies[model]}")
            
            # res.partner NO depende de res.users
            # IMPORTANTE: user_id en res.partner se establece a False si no hay mapeo, NO requiere res.users
            # res.partner se migra PRIMERO, luego res.users puede crear partners automáticamente si no existen
            if model == 'res.partner':
                # Eliminar dependencia de res.users - res.partner puede crearse sin user_id
                if 'res.users' in dependencies[model]:
                    dependencies[model].remove('res.users')
                    logger.debug(f"[DEPENDENCIAS] Removida dependencia de res.users de {model} (user_id se establece a False si no hay mapeo)")
                # Limpiar dependencias circulares incorrectas
                if 'res.partner' in dependencies[model]:
                    dependencies[model].remove('res.partner')
                    logger.debug(f"[DEPENDENCIAS] Removida dependencia circular res.partner de {model}")
                # Limpiar dependencias circulares con crm.team y product.pricelist
                if 'crm.team' in dependencies[model]:
                    dependencies[model].remove('crm.team')
                    logger.debug(f"[DEPENDENCIAS] Removida dependencia circular crm.team de {model}")
                if 'product.pricelist' in dependencies[model]:
                    dependencies[model].remove('product.pricelist')
                    logger.debug(f"[DEPENDENCIAS] Removida dependencia circular product.pricelist de {model}")
                logger.debug(f"[DEPENDENCIAS] Dependencias explícitas para {model}: {dependencies[model]}")
            
            # res.users depende de res.partner (partner_id apunta a res.partner)
            # IMPORTANTE: res.partner se migra PRIMERO, luego res.users puede crear partners automáticamente si no existen
            # Para evitar dependencias circulares, res.partner NO depende de res.users (user_id se establece a False)
            if model == 'res.users':
                # Mantener dependencia de res.partner - res.users necesita partners
                # Si res.partner está en models_list, mantener la dependencia
                if 'res.partner' in model_names and 'res.partner' not in dependencies[model]:
                    dependencies[model].append('res.partner')
                    logger.debug(f"[DEPENDENCIAS] Agregada dependencia explícita: {model} -> res.partner (res.partner se migra primero)")
                # Limpiar dependencias circulares con crm.team y product.pricelist
                # Estos modelos pueden tener campos que apuntan a res.users, pero res.users debe migrarse después de res.partner
                if 'crm.team' in dependencies[model]:
                    dependencies[model].remove('crm.team')
                    logger.debug(f"[DEPENDENCIAS] Removida dependencia circular crm.team de {model}")
                if 'product.pricelist' in dependencies[model]:
                    dependencies[model].remove('product.pricelist')
                    logger.debug(f"[DEPENDENCIAS] Removida dependencia circular product.pricelist de {model}")
                # Limpiar dependencia circular consigo mismo
                if 'res.users' in dependencies[model]:
                    dependencies[model].remove('res.users')
                    logger.debug(f"[DEPENDENCIAS] Removida dependencia circular res.users de {model}")
                logger.debug(f"[DEPENDENCIAS] Dependencias explícitas para {model}: {dependencies[model]}")
            
            # crm.lead depende de res.partner, crm.team, crm.stage
            if model == 'crm.lead':
                if 'res.partner' in model_names and 'res.partner' not in dependencies[model]:
                    dependencies[model].append('res.partner')
                if 'crm.team' in model_names and 'crm.team' not in dependencies[model]:
                    dependencies[model].append('crm.team')
                if 'crm.stage' in model_names and 'crm.stage' not in dependencies[model]:
                    dependencies[model].append('crm.stage')
                logger.debug(f"[DEPENDENCIAS] Dependencias explícitas para {model}: {dependencies[model]}")
        
        # Log de dependencias antes del ordenamiento
        logger.debug("[DEPENDENCIAS] Dependencias detectadas:")
        for model, deps in dependencies.items():
            if deps:
                logger.debug(f"  {model} -> {deps}")
        
        # Topological sort
        sorted_models = []
        visited = set()
        temp_visited = set()
        
        def visit(model):
            if model in temp_visited:
                logger.warning(f"⚠ Dependencia circular detectada para {model}")
                # En caso de dependencia circular, simplemente retornar sin agregar
                # El modelo se agregará cuando se procese desde otro camino
                return
            if model in visited:
                return
            
            temp_visited.add(model)
            
            # Procesar dependencias en orden
            for dep in dependencies.get(model, []):
                if dep in model_config_map:
                    visit(dep)
                else:
                    logger.debug(f"[DEPENDENCIAS] Dependencia {dep} de {model} no está en models_config, omitiendo")
            
            temp_visited.remove(model)
            visited.add(model)
            sorted_models.append(model_config_map[model])
        
        # Procesar modelos en orden, asegurando que los modelos sin dependencias se procesen primero
        # Ordenar modelos por número de dependencias (menos dependencias primero)
        models_by_dep_count = sorted(
            models_config,
            key=lambda m: len(dependencies.get(m['model'], []))
        )
        
        for model_config in models_by_dep_count:
            model = model_config['model']
            if model not in visited:
                visit(model)
        
        # Si hay modelos que no se agregaron (por dependencias circulares), agregarlos al final
        for model_config in models_config:
            model = model_config['model']
            if model not in visited:
                logger.warning(f"⚠ Modelo {model} no se agregó durante el ordenamiento topológico, agregándolo al final")
                sorted_models.append(model_config)
        
        logger.info(f"✓ Modelos ordenados por dependencias ({len(sorted_models)} modelos):")
        for i, m in enumerate(sorted_models, 1):
            deps = dependencies.get(m['model'], [])
            deps_str = f" (depende de: {', '.join(deps)})" if deps else " (sin dependencias)"
            logger.info(f"  {i:2d}. {m['model']}{deps_str}")
        
        return sorted_models
    
    def get_many2one_fields_info(self, model: str, conn: OdooConnection) -> Dict[str, str]:
        """
        Obtiene información de campos many2one y su modelo relacionado.
        
        Args:
            model: Nombre del modelo
            conn: Conexión Odoo
        
        Returns:
            Diccionario {field_name: relation_model}
        """
        many2one_fields = {}
        try:
            fields_info = conn.get_fields(model)
            
            for field_name, field_info in fields_info.items():
                field_type = field_info.get('type', '')
                if field_type == 'many2one':
                    relation = field_info.get('relation', '')
                    if relation:
                        many2one_fields[field_name] = relation
            
            return many2one_fields
        except Exception as e:
            logger.warning(f"⚠ No se pudieron obtener campos many2one de {model}: {e}")
            return {}
    
    def _find_or_create_m2o_by_name(self, relation_model: str, search_field: str, 
                                     search_value: str, create_if_not_exists: bool = False,
                                     additional_data: Dict[str, Any] = None) -> int:
        """
        Busca un registro en un modelo relacionado por nombre. Si no existe y create_if_not_exists=True, lo crea.
        
        Args:
            relation_model: Nombre del modelo relacionado
            search_field: Campo por el cual buscar (normalmente 'name')
            search_value: Valor a buscar
            create_if_not_exists: Si True, crea el registro si no existe
            additional_data: Datos adicionales para usar al crear el registro (ej: country_id para res.country.state)
        
        Returns:
            ID del registro encontrado o creado, o False si no se encontró/creó
        """
        if not search_value or not isinstance(search_value, str):
            return False
        
        try:
            # Buscar el registro por nombre
            domain = [[search_field, '=', search_value]]
            found_ids = self.v18_conn.models.execute_kw(
                self.v18_conn.db, self.v18_conn.uid, self.v18_conn.password,
                relation_model, 'search',
                [domain],
                {'limit': 1}
            )
            
            if found_ids:
                return found_ids[0]
            
            # Para res.country.state, también buscar por código si el nombre contiene código
            # Ejemplo: "Madrid (ES)" -> código podría ser "ES-M" o similar
            # O buscar por código extraído del nombre
            if relation_model == 'res.country.state':
                # Intentar extraer código del nombre (formato común: "Nombre (CODE)" o "Nombre (CODE-XX)")
                import re
                code_match = re.search(r'\(([A-Z0-9\-]+)\)', search_value)
                if code_match:
                    state_code = code_match.group(1)
                    # Buscar por código, pero necesitamos country_id también
                    if additional_data and 'country_id' in additional_data:
                        country_id = additional_data['country_id']
                        code_domain = [['code', '=', state_code], ['country_id', '=', country_id]]
                        code_found_ids = self.v18_conn.models.execute_kw(
                            self.v18_conn.db, self.v18_conn.uid, self.v18_conn.password,
                            relation_model, 'search',
                            [code_domain],
                            {'limit': 1}
                        )
                        if code_found_ids:
                            logger.info(f"[M2O BY NAME] Encontrado estado por código '{state_code}' para país {country_id}, ID: {code_found_ids[0]}")
                            return code_found_ids[0]
                    else:
                        # Si no hay country_id en additional_data, buscar solo por código
                        # (puede haber duplicados entre países, pero es mejor que fallar)
                        code_domain = [['code', '=', state_code]]
                        code_found_ids = self.v18_conn.models.execute_kw(
                            self.v18_conn.db, self.v18_conn.uid, self.v18_conn.password,
                            relation_model, 'search',
                            [code_domain],
                            {'limit': 1}
                        )
                        if code_found_ids:
                            logger.info(f"[M2O BY NAME] Encontrado estado por código '{state_code}' (sin country_id), ID: {code_found_ids[0]}")
                            return code_found_ids[0]
            
            # Si no existe y create_if_not_exists=True, crear el registro
            if create_if_not_exists:
                logger.info(f"[M2O BY NAME] Creando registro en {relation_model} con {search_field}='{search_value}'")
                try:
                    # Obtener campos requeridos del modelo relacionado
                    relation_fields = self.v18_conn.get_fields(relation_model)
                    create_data = {search_field: search_value}
                    
                    # Agregar campos requeridos adicionales
                    for field_name, field_info in relation_fields.items():
                        if field_info.get('required', False) and field_name != search_field:
                            field_type = field_info.get('type', '')
                            
                            # Intentar obtener valor desde additional_data
                            if additional_data and field_name in additional_data:
                                create_data[field_name] = additional_data[field_name]
                                logger.debug(f"[M2O BY NAME] Usando {field_name}={additional_data[field_name]} desde additional_data")
                            elif field_type == 'many2one':
                                # Para campos many2one requeridos, intentar buscar por nombre si está en additional_data
                                relation = field_info.get('relation', '')
                                if additional_data and f"{field_name}_name" in additional_data:
                                    # Buscar el registro relacionado por nombre
                                    related_name = additional_data[f"{field_name}_name"]
                                    related_id = self._find_or_create_m2o_by_name(
                                        relation, 'name', related_name, create_if_not_exists=True,
                                        additional_data=additional_data
                                    )
                                    if related_id:
                                        create_data[field_name] = related_id
                                    else:
                                        logger.warning(f"[M2O BY NAME] ⚠ No se pudo obtener {field_name} para {relation_model}, omitiendo creación")
                                        return False
                                # Para res.country.state, si no hay country_id en additional_data, buscar país por defecto
                                elif relation_model == 'res.country.state' and field_name == 'country_id':
                                    logger.warning(f"[M2O BY NAME] ⚠ Campo requerido {field_name} no encontrado en additional_data para {relation_model}, buscando país por defecto")
                                    # Buscar país España (ES) como fallback
                                    country_domain = [['code', '=', 'ES']]
                                    country_ids = self.v18_conn.models.execute_kw(
                                        self.v18_conn.db, self.v18_conn.uid, self.v18_conn.password,
                                        'res.country', 'search',
                                        [country_domain],
                                        {'limit': 1}
                                    )
                                    if country_ids:
                                        create_data[field_name] = country_ids[0]
                                        logger.info(f"[M2O BY NAME] Usando país por defecto (ES) con ID: {country_ids[0]}")
                                    else:
                                        logger.error(f"[M2O BY NAME] ✗ No se encontró país por defecto (ES) para crear estado '{search_value}'")
                                        return False
                                else:
                                    logger.warning(f"[M2O BY NAME] ⚠ Campo requerido {field_name} no encontrado en additional_data para {relation_model}")
                                    return False
                            else:
                                # Para otros tipos, usar valor por defecto según el tipo
                                if field_type in ['integer', 'float']:
                                    create_data[field_name] = 0
                                elif field_type == 'boolean':
                                    create_data[field_name] = False
                                elif field_type in ['char', 'text']:
                                    create_data[field_name] = ""
                                else:
                                    logger.warning(f"[M2O BY NAME] ⚠ Campo requerido {field_name} de tipo {field_type} sin valor por defecto para {relation_model}")
                                    return False
                    
                    logger.debug(f"[M2O BY NAME] Datos de creación para {relation_model}: {create_data}")
                    
                    try:
                        created_id = self.v18_conn.models.execute_kw(
                            self.v18_conn.db, self.v18_conn.uid, self.v18_conn.password,
                            relation_model, 'create',
                            [create_data]
                        )
                        logger.info(f"[M2O BY NAME] ✓ Registro creado en {relation_model} con ID: {created_id}")
                        return created_id
                    except Exception as create_error:
                        error_str = str(create_error)
                        # Si el error es que el código ya existe (para res.country.state)
                        if relation_model == 'res.country.state' and 'code' in error_str.lower() and ('unique' in error_str.lower() or 'duplicate' in error_str.lower()):
                            logger.warning("[M2O BY NAME] ⚠ El código del estado ya existe, buscando estado existente...")
                            # Intentar buscar el estado por código
                            if 'code' in create_data:
                                state_code = create_data['code']
                                country_id = create_data.get('country_id')
                                
                                if country_id:
                                    # Buscar por código y país
                                    code_domain = [['code', '=', state_code], ['country_id', '=', country_id]]
                                else:
                                    # Buscar solo por código
                                    code_domain = [['code', '=', state_code]]
                                
                                existing_ids = self.v18_conn.models.execute_kw(
                                    self.v18_conn.db, self.v18_conn.uid, self.v18_conn.password,
                                    relation_model, 'search',
                                    [code_domain],
                                    {'limit': 1}
                                )
                                
                                if existing_ids:
                                    logger.info(f"[M2O BY NAME] ✓ Estado encontrado por código '{state_code}' (ya existía), ID: {existing_ids[0]}")
                                    return existing_ids[0]
                                else:
                                    logger.error(f"[M2O BY NAME] ✗ Error indica que el código existe pero no se encontró: {create_error}")
                                    return False
                        else:
                            # Para otros errores, lanzar la excepción
                            raise create_error
                except Exception as e:
                    logger.error(f"[M2O BY NAME] ✗ Error creando registro en {relation_model} con {search_field}='{search_value}': {e}")
                    return False
            
            return False
        except Exception as e:
            logger.warning(f"[M2O BY NAME] ⚠ Error buscando en {relation_model} con {search_field}='{search_value}': {e}")
            return False
    
    def has_parent_id(self, model: str, conn: OdooConnection) -> bool:
        """
        Verifica si un modelo tiene el campo parent_id.
        
        Args:
            model: Nombre del modelo
            conn: Conexión Odoo
        
        Returns:
            True si tiene parent_id, False en caso contrario
        """
        try:
            fields_info = conn.get_fields(model)
            return 'parent_id' in fields_info
        except Exception as e:
            logger.warning(f"⚠ No se pudo verificar parent_id para {model}: {e}")
            return False
    
    def sort_records_by_parent(self, records: List[Dict], v13_ids: List[int]) -> tuple:
        """
        Ordena registros: primero los que no tienen parent_id, luego los que sí tienen.
        
        Args:
            records: Lista de registros
            v13_ids: Lista de IDs v13 correspondientes
        
        Returns:
            Tupla (records_ordenados, v13_ids_ordenados)
        """
        records_without_parent = []
        ids_without_parent = []
        records_with_parent = []
        ids_with_parent = []
        
        for record, v13_id in zip(records, v13_ids):
            parent_id = record.get('parent_id', False)
            
            # Verificar si tiene parent_id (puede ser False, None, o [id, name])
            has_parent = False
            if parent_id:
                if isinstance(parent_id, (list, tuple)) and len(parent_id) > 0:
                    has_parent = True
                elif isinstance(parent_id, (int, str)) and parent_id:
                    has_parent = True
            
            if has_parent:
                records_with_parent.append(record)
                ids_with_parent.append(v13_id)
            else:
                records_without_parent.append(record)
                ids_without_parent.append(v13_id)
        
        # Primero los sin parent, luego los con parent
        sorted_records = records_without_parent + records_with_parent
        sorted_ids = ids_without_parent + ids_with_parent
        
        logger.info(f"  Ordenados: {len(records_without_parent)} sin parent_id, {len(records_with_parent)} con parent_id")
        
        return sorted_records, sorted_ids
    
    def prepare_records_for_creation(self, records: List[Dict], model: str, 
                                   models_list: List[str] = None) -> List[Dict]:
        """
        Prepara registros para creación en v18, validando campos y limpiando datos inválidos.
        También mapea campos many2many que vienen como arrays simples de IDs (ej: category_id: [3]).
        
        Args:
            records: Lista de registros a preparar
            model: Nombre del modelo
            models_list: Lista de modelos a migrar (para mapear relaciones many2many)
        
        Returns:
            Lista de registros preparados y validados
        """
        if not records:
            return []
        
        # Obtener campos válidos del modelo en v18
        try:
            v18_fields = self.v18_conn.get_fields(model)
            valid_field_names = set(v18_fields.keys())
            
            # Campos que siempre debemos excluir
            system_fields = {'id', 'create_uid', 'write_uid', 'create_date', 'write_date'}
            
            # Identificar campos readonly y computed sin store
            readonly_fields = set()
            computed_fields = set()
            no_store_fields = set()  # Campos sin store (computed) que no se pueden establecer en create()
            
            for field_name, field_info in v18_fields.items():
                # NUNCA excluir 'name' aunque sea readonly (es requerido y debe tener valor)
                if field_info.get('readonly', False) and field_name != 'name':
                    readonly_fields.add(field_name)
                # Los campos computed sin store no deben incluirse (excepto name si es requerido)
                if field_info.get('type') in ['one2many', 'many2many'] and field_name != 'name':
                    computed_fields.add(field_name)
                # Excluir campos sin store (computed) - no se pueden establecer en create()
                # EXCEPCIÓN: 'name' en res.users aunque sea computed (se necesita para crear el usuario)
                if not field_info.get('store', True) and field_name != 'name':
                    no_store_fields.add(field_name)
            
            prepared_records = []
            removed_fields_count = {}
            
            # Log de diagnóstico para uom.uom
            if model == 'uom.uom' and records:
                first_record = records[0]
                if 'category_id' in first_record:
                    logger.info(f"[DIAGNÓSTICO] Primer registro de uom.uom, category_id ANTES de prepare_records_for_creation: {first_record['category_id']} (tipo: {type(first_record['category_id'])})")
            
            # Identificar campos requeridos en v18
            required_fields = set()
            for field_name, field_info in v18_fields.items():
                if field_info.get('required', False):
                    required_fields.add(field_name)
            
            # IDs de stages para sale.subscription (obtenidos directamente de la DB)
            # In progress = 3, Closed = 4
            IN_PROGRESS_STAGE_ID = 3
            CLOSED_STAGE_ID = 4
            
            if model == 'sale.subscription' and 'stage_id' in valid_field_names:
                logger.info(f"  [ESTADO] IDs de stages para sale.subscription: In progress={IN_PROGRESS_STAGE_ID}, Closed={CLOSED_STAGE_ID}")
            
            for record in records:
                prepared_record = {}
                # Almacenar campos many2many para aplicarlos después con write
                m2m_fields = {}
                
                # IMPORTANTE: Guardar el ID del registro v13 ANTES de procesarlo
                # porque el campo 'id' se excluirá más adelante
                record_v13_id = record.get('id', 'Unknown')
                
                # PASO 0: Asegurar que campos requeridos críticos tengan valores ANTES de procesar otros campos
                # Esto es especialmente importante para 'name' en res.partner
                if 'name' in required_fields:
                    name_value = record.get('name')
                    record_id = record.get('id', 'Unknown')
                    
                    # Verificar si name está vacío o no existe
                    is_name_empty = (name_value is None or 
                                   name_value is False or 
                                   (isinstance(name_value, str) and not name_value.strip()))
                    
                    if is_name_empty:
                        if model == 'res.partner':
                            # Intentar usar display_name como fallback
                            display_name = record.get('display_name')
                            
                            if display_name and isinstance(display_name, str) and display_name.strip():
                                prepared_record['name'] = display_name
                            else:
                                # Para res.partner, usar espacio en blanco si no hay nombre
                                prepared_record['name'] = " "
                        else:
                            prepared_record['name'] = f"{model} {record_id}"
                        logger.debug(f"  [PRE-ASIGNACIÓN] Campo 'name' vacío en {model} (ID: {record_id}), asignado: {prepared_record['name']}")
                    else:
                        # name tiene un valor válido, guardarlo para procesarlo después
                        prepared_record['name'] = name_value
                
                for field_name, field_value in record.items():
                    # Excluir campos del sistema
                    if field_name in system_fields:
                        continue
                    
                    # Excluir campos que no existen en v18
                    if field_name not in valid_field_names:
                        removed_fields_count[field_name] = removed_fields_count.get(field_name, 0) + 1
                        continue
                    
                    # Excluir campos readonly (PRIMERO, antes de procesar valores)
                    if field_name in readonly_fields:
                        removed_fields_count[field_name] = removed_fields_count.get(field_name, 0) + 1
                        continue
                    
                    # Excluir campos computed (one2many, many2many) (PRIMERO, antes de procesar valores)
                    if field_name in computed_fields:
                        removed_fields_count[field_name] = removed_fields_count.get(field_name, 0) + 1
                        continue
                    
                    # Excluir campos sin store (computed) - no se pueden establecer en create() (CRÍTICO: ANTES de procesar valores)
                    # Estos campos pueden tener valores pero no se pueden establecer en create()
                    if field_name in no_store_fields:
                        removed_fields_count[field_name] = removed_fields_count.get(field_name, 0) + 1
                        continue
                    
                    # Excluir campos many2many explícitamente (no se pueden establecer en create)
                    field_info_check = v18_fields.get(field_name, {})
                    if field_info_check.get('type') == 'many2many':
                        removed_fields_count[field_name] = removed_fields_count.get(field_name, 0) + 1
                        continue
                    
                    # Si 'name' ya fue pre-asignado, actualizarlo con el valor del registro si es válido
                    if field_name == 'name' and 'name' in prepared_record:
                        # Si el valor del registro es válido, usarlo; si no, mantener el pre-asignado
                        is_empty = (field_value is None or 
                                   field_value is False or 
                                   (isinstance(field_value, str) and not field_value.strip()))
                        if not is_empty:
                            prepared_record['name'] = field_value
                        # Continuar para procesar otros campos, pero name ya está asignado
                        continue
                    
                    # Convertir valores booleanos de JSON (true/false) a Python (True/False)
                    # Esto es necesario porque JSON puede tener valores booleanos que no son válidos en Python
                    if isinstance(field_value, bool):
                        # Mantener el valor booleano tal cual
                        pass
                    elif field_value == "false" or field_value == "False":
                        field_value = False
                    elif field_value == "true" or field_value == "True":
                        field_value = True
                    
                    # Manejar valores None o vacíos: solo incluir si el campo no es required
                    # Verificar si el valor es None, False, o cadena vacía
                    is_empty = (field_value is None or 
                               field_value is False or 
                               (isinstance(field_value, str) and not field_value.strip()))
                    
                    if is_empty:
                        field_info = v18_fields.get(field_name, {})
                        if field_info.get('required', False):
                            # Si es required y está vacío, intentar usar valor por defecto o False
                            field_type = field_info.get('type', '')
                            
                            # Casos especiales para campos requeridos comunes
                            if field_name == 'name':
                                # name es requerido en muchos modelos, usar un valor por defecto
                                record_id = record.get('id', 'Unknown')
                                if model == 'res.partner':
                                    # Intentar usar display_name como fallback
                                    display_name = record.get('display_name')
                                    
                                    if display_name and isinstance(display_name, str) and display_name.strip():
                                        field_value = display_name
                                    else:
                                        # Para res.partner, usar espacio en blanco si no hay nombre
                                        field_value = " "
                                else:
                                    field_value = f"{model} {record_id}"
                                logger.debug(f"  Campo 'name' null/vacío en {model}, usando valor por defecto: {field_value}")
                            elif field_type == 'many2one':
                                # Para campos many2one requeridos, usar False (Odoo creará el valor por defecto si es necesario)
                                # Caso especial: company_id en res.users debe tener un valor si es requerido
                                # (aunque res.company no esté en models_to_migrate.txt)
                                if field_name == 'company_id' and model == 'res.users':
                                    # Buscar la compañía principal (normalmente la primera o la que tiene id=1)
                                    try:
                                        company_domain = []
                                        companies = self.v18_conn.search_read('res.company', company_domain, ['id'], limit=1)
                                        if companies:
                                            field_value = companies[0]['id']
                                            logger.debug(f"  Campo requerido {field_name} en {model} sin valor (res.company no migrado), usando compañía por defecto: {field_value}")
                                        else:
                                            # Si no hay compañías, usar False y dejar que Odoo use su valor por defecto
                                            field_value = False
                                            logger.warning(f"  ⚠ No se encontró compañía por defecto para {field_name} en {model}, usando False")
                                    except Exception as e:
                                        logger.warning(f"  ⚠ Error buscando compañía por defecto para {field_name} en {model}: {e}, usando False")
                                        field_value = False
                                # Caso especial: alias_id en crm.team es requerido pero puede ser False
                                elif field_name == 'alias_id' and model == 'crm.team':
                                    field_value = False
                                    logger.debug(f"  Campo requerido {field_name} en {model} sin valor, usando False (Odoo creará el alias automáticamente)")
                                else:
                                    field_value = False
                            elif field_type in ['integer', 'float']:
                                field_value = 0
                            elif field_type == 'boolean':
                                field_value = False
                            elif field_type == 'selection':
                                # Para campos selection requeridos, usar valores por defecto según el modelo
                                if model in ['product.template', 'product.product']:
                                    if field_name == 'service_tracking':
                                        field_value = 'no'
                                    elif field_name == 'purchase_line_warn':
                                        field_value = 'no-message'
                                    elif field_name == 'sale_line_warn':
                                        field_value = 'no-message'
                                    else:
                                        field_value = False
                                elif model == 'product.pricelist.item':
                                    if field_name == 'display_applied_on':
                                        # Mapear desde applied_on
                                        applied_on = record.get('applied_on', '')
                                        if applied_on == '1_product':
                                            field_value = '1_product'
                                        elif applied_on == '2_product_category':
                                            field_value = '2_product_category'
                                        elif applied_on == '0_product_variant':
                                            field_value = '1_product'  # Product variant -> Product
                                        elif applied_on == '3_global':
                                            field_value = '1_product'  # Global -> Product (por defecto)
                                        else:
                                            field_value = '1_product'  # Valor por defecto
                                    else:
                                        field_value = False
                                else:
                                    field_value = False
                            elif field_type in ['char', 'text']:
                                # Para campos de texto requeridos, usar valor por defecto
                                if field_name == 'name':
                                    record_id = record.get('id', 'Unknown')
                                    field_value = f"{model} {record_id}"
                                else:
                                    field_value = ""
                            else:
                                # Para otros tipos, intentar usar valor por defecto según el tipo
                                if field_type in ['date', 'datetime']:
                                    continue  # Omitir fechas null requeridas
                                else:
                                    field_value = ""
                        else:
                            # Si no es required, omitir el campo si está vacío
                            continue
                    
                    # Manejar campos many2many que vienen como arrays simples (ej: category_id: [3])
                    # Estos campos necesitan mapeo de IDs de v13 a v18
                    # EXCEPCIÓN: category_id para uom.uom se procesa más adelante con mapeo especial
                    if isinstance(field_value, list) and len(field_value) > 0:
                        # Excluir category_id para uom.uom (se procesa con mapeo especial más adelante)
                        if field_name == 'category_id' and model == 'uom.uom':
                            # No procesar aquí, continuar para que se procese con el mapeo especial
                            pass
                        else:
                            # Verificar si es un array simple de IDs (no tuplas)
                            if all(isinstance(item, (int, str)) and not isinstance(item, (list, tuple)) for item in field_value):
                                # Es un array simple de IDs, verificar si necesita mapeo
                                field_info_check = v18_fields.get(field_name, {})
                                field_type_check = field_info_check.get('type', '')
                                
                                # Si es many2many o many2one, mapear cada ID
                                if field_type_check in ['many2many', 'many2one']:
                                    # Obtener el modelo relacionado
                                    relation_model = field_info_check.get('relation', '')
                                if relation_model and models_list and relation_model in models_list:
                                    # Obtener mapeo para el modelo relacionado
                                    relation_mapping = self.v18_conn.get_migration_mapping(relation_model)
                                    if relation_mapping:
                                        # Mapear cada ID del array
                                        mapped_ids = []
                                        for v13_id in field_value:
                                            v13_id_str = str(v13_id)
                                            if v13_id_str in relation_mapping:
                                                v18_id = relation_mapping[v13_id_str]
                                                mapped_ids.append(v18_id)
                                            else:
                                                logger.debug(f"  No se encontró mapeo para {field_name}={v13_id} en {relation_model}, omitiendo")
                                        # Para many2many, guardar los IDs mapeados para aplicarlos después con write
                                        # NO incluirlos en el registro preparado (se aplicarán después)
                                        if field_type_check == 'many2many':
                                            if mapped_ids:
                                                # Guardar para aplicar después con write usando comando [(6, 0, [ids])]
                                                m2m_fields[field_name] = mapped_ids
                                                logger.info(f"  [M2M] ✓ Guardados {len(mapped_ids)} IDs mapeados para {field_name} de {model} -> {relation_model} (v13: {field_value} -> v18: {mapped_ids})")
                                                # NO incluir este campo en prepared_record (se aplicará después)
                                                continue
                                            else:
                                                logger.warning(f"  [M2M] ⚠ No se encontraron mapeos para {field_name} en {model} (IDs v13: {field_value}), se omitirá")
                                                # NO incluir este campo en prepared_record
                                                continue
                                        else:
                                            # Para many2one, actualizar el valor normalmente
                                            if mapped_ids:
                                                field_value = mapped_ids[0] if mapped_ids else False
                                                logger.debug(f"  Mapeados {len(mapped_ids)} IDs en {field_name} de {model} (many2one)")
                                            else:
                                                field_value = False
                                                logger.debug(f"  No se encontraron mapeos para {field_name} en {model}, usando False")
                    
                    # Aplicar mapeos de campos si existen
                    if model in self.field_mappings:
                        model_mappings = self.field_mappings[model]
                        if field_name in model_mappings:
                            mapping = model_mappings[field_name]
                            # El mapeo es un diccionario con valores a mapear
                            if isinstance(mapping, dict):
                                # Buscar el valor en el mapeo (ignorar 'description' y 'default' si existen)
                                field_value_str = str(field_value) if field_value is not None else 'None'
                                if field_value_str in mapping and field_value_str not in ['description', 'default']:
                                    new_value = mapping[field_value_str]
                                    logger.debug(f"  Mapeando {model}.{field_name}: '{field_value}' -> '{new_value}'")
                                    field_value = new_value
                                elif 'default' in mapping and field_value_str not in mapping:
                                    # Si hay un valor por defecto y el valor actual no está en el mapeo
                                    logger.debug(f"  Usando valor por defecto para {model}.{field_name}: '{mapping['default']}'")
                                    field_value = mapping['default']
                    
                    # Convertir campos many2one que vienen como tuplas [id, name] a solo el ID
                    # EXCEPCIÓN: category_id para uom.uom se procesa más adelante con mapeo especial
                    field_info = v18_fields.get(field_name, {})
                    if field_info.get('type') == 'many2one':
                        # Excluir category_id para uom.uom (se procesa con mapeo especial más adelante)
                        if field_name == 'category_id' and model == 'uom.uom':
                            # No procesar aquí, continuar para que se procese con el mapeo especial
                            pass
                        else:
                            # Si el valor es una tupla [id, name], extraer solo el ID
                            if isinstance(field_value, list) and len(field_value) >= 1:
                                # Es una tupla many2one, extraer el ID
                                field_value = field_value[0] if field_value[0] else False
                                logger.debug(f"  Campo many2one {field_name} convertido de tupla a ID: {field_value}")
                        
                        # Verificar si este campo debe buscarse/crearse por nombre
                        if model in self.m2o_fields_by_name and field_name in self.m2o_fields_by_name[model]:
                            m2o_config = self.m2o_fields_by_name[model][field_name]
                            relation_model = m2o_config.get('model')
                            search_field = m2o_config.get('search_field', 'name')
                            create_if_not_exists = m2o_config.get('create_if_not_exists', False)
                            
                            # Obtener el nombre del registro relacionado desde v13
                            # El field_value puede venir como ID o como tupla [id, name]
                            related_name = None
                            
                            if isinstance(field_value, list) and len(field_value) >= 2:
                                # Formato tupla: [id, name]
                                related_name = field_value[1] if isinstance(field_value[1], str) else None
                            elif isinstance(field_value, (int, str)) and field_value:
                                # Es un ID, intentar obtener el nombre desde el registro original
                                # Buscar en el registro si hay información del campo relacionado
                                related_record_key = f"{field_name}_name"  # Algunos campos tienen _name
                                if related_record_key in record:
                                    related_name = record[related_record_key]
                                else:
                                    # Intentar obtener desde el campo display_name del relacionado
                                    logger.debug(f"  Campo {field_name} tiene ID {field_value}, pero no se encontró nombre en el registro")
                            
                            # Para res.country.state, necesitamos obtener country_id desde el registro
                            # Intentar obtener country_id desde el registro de res.partner
                            country_id_v18 = None
                            if relation_model == 'res.country.state':
                                # Buscar country_id en el registro
                                if 'country_id' in record:
                                    country_id_v13 = record['country_id']
                                    # country_id puede venir como [id, name] o como ID
                                    if isinstance(country_id_v13, list) and len(country_id_v13) >= 1:
                                        country_id_v13_value = country_id_v13[0]
                                        country_id_v13_name = country_id_v13[1] if len(country_id_v13) >= 2 else None
                                    elif isinstance(country_id_v13, (int, str)):
                                        country_id_v13_value = country_id_v13
                                        country_id_v13_name = record.get('country_id_name')
                                    else:
                                        country_id_v13_value = None
                                        country_id_v13_name = None
                                    
                                    if country_id_v13_value:
                                        # Intentar buscar país por nombre primero
                                        if country_id_v13_name:
                                            country_id_v18 = self._find_or_create_m2o_by_name(
                                                'res.country', 'name', country_id_v13_name, 
                                                create_if_not_exists=True
                                            )
                                        
                                        # Si no se encontró por nombre, intentar por ID usando migration.tracking
                                        if not country_id_v18:
                                            country_mapping = self.v18_conn.get_migration_mapping('res.country')
                                            if country_mapping:
                                                country_id_str = str(country_id_v13_value)
                                                if country_id_str in country_mapping:
                                                    country_id_v18 = country_mapping[country_id_str]
                                        
                                        if not country_id_v18:
                                            logger.warning(f"  No se pudo obtener country_id para estado '{related_name}', se intentará usar país por defecto")
                            
                            if related_name:
                                # Buscar por nombre en v18
                                # Pasar country_id como additional_data si está disponible
                                additional_data = {}
                                if country_id_v18:
                                    additional_data['country_id'] = country_id_v18
                                
                                v18_id = self._find_or_create_m2o_by_name(
                                    relation_model, 
                                    search_field, 
                                    related_name, 
                                    create_if_not_exists,
                                    additional_data
                                )
                                if v18_id:
                                    field_value = v18_id
                                    logger.debug(f"  Campo {field_name} mapeado por nombre '{related_name}' -> ID v18: {v18_id}")
                                else:
                                    field_value = False
                                    logger.warning(f"  No se pudo encontrar/crear registro en {relation_model} con {search_field}='{related_name}'")
                            else:
                                # Si no hay nombre, usar False
                                field_value = False
                                logger.debug(f"  Campo {field_name} no tiene nombre, usando False")
                    
                    # Verificar nuevamente si el valor es vacío después del mapeo (especialmente para campos requeridos)
                    field_info = v18_fields.get(field_name, {})
                    if field_info.get('required', False):
                        is_empty_after_mapping = (field_value is None or 
                                                 field_value is False or 
                                                 (isinstance(field_value, str) and not field_value.strip()))
                        
                        # Caso especial: company_id requerido en res.users
                        if is_empty_after_mapping and field_name == 'company_id' and model == 'res.users':
                            # Buscar la compañía principal
                            try:
                                company_domain = []
                                companies = self.v18_conn.search_read('res.company', company_domain, ['id'], limit=1)
                                if companies:
                                    field_value = companies[0]['id']
                                    logger.debug(f"  Campo requerido {field_name} en {model} sin valor después del mapeo, usando compañía por defecto: {field_value}")
                                else:
                                    logger.warning(f"  ⚠ No se encontró compañía por defecto para {field_name} en {model} después del mapeo")
                            except Exception as e:
                                logger.warning(f"  ⚠ Error buscando compañía por defecto para {field_name} en {model} después del mapeo: {e}")
                        
                        if is_empty_after_mapping and field_name == 'name':
                            # Si name sigue vacío después del mapeo, asignar valor por defecto
                            record_id = record.get('id', 'Unknown')
                            if model == 'res.partner':
                                display_name = record.get('display_name')
                                
                                if display_name and isinstance(display_name, str) and display_name.strip():
                                    field_value = display_name
                                else:
                                    # Para res.partner, usar espacio en blanco si no hay nombre
                                    field_value = " "
                            else:
                                field_value = f"{model} {record_id}"
                            logger.debug(f"  Campo 'name' quedó vacío después del mapeo en {model}, usando valor por defecto: {field_value}")
                        
                        # Caso especial: company_id requerido en res.users
                        if is_empty_after_mapping and field_name == 'company_id' and model == 'res.users':
                            # Buscar la compañía principal
                            try:
                                company_domain = []
                                companies = self.v18_conn.search_read('res.company', company_domain, ['id'], limit=1)
                                if companies:
                                    field_value = companies[0]['id']
                                    logger.debug(f"  [POST-MAPEO] Campo requerido {field_name} en {model} sin valor después del mapeo, usando compañía por defecto: {field_value}")
                                else:
                                    logger.warning(f"  ⚠ [POST-MAPEO] No se encontró compañía por defecto para {field_name} en {model} después del mapeo")
                            except Exception as e:
                                logger.warning(f"  ⚠ [POST-MAPEO] Error buscando compañía por defecto para {field_name} en {model} después del mapeo: {e}")
                    
                    # Verificación final para company_id en res.users antes de incluir
                    # (res.company no está en models_to_migrate.txt, pero company_id es requerido en v18)
                    if field_name == 'company_id' and model == 'res.users':
                        # Asegurar que company_id no sea False o None si es requerido
                        if (field_value is None or field_value is False) and field_info.get('required', False):
                            try:
                                company_domain = []
                                companies = self.v18_conn.search_read('res.company', company_domain, ['id'], limit=1)
                                if companies:
                                    field_value = companies[0]['id']
                                    logger.debug(f"  [FINAL] Campo {field_name} en {model} era False/None (res.company no migrado), asignada compañía por defecto: {field_value}")
                                else:
                                    logger.warning(f"  ⚠ [FINAL] No se encontró compañía por defecto para {field_name} en {model}")
                            except Exception as e:
                                logger.warning(f"  ⚠ [FINAL] Error buscando compañía por defecto para {field_name} en {model}: {e}")
                    
                    # Aplicar mapeos específicos para currency, uom y pricelist ANTES de procesar many2one
                    field_info_check = v18_fields.get(field_name, {})
                    if field_info_check.get('type') == 'many2one':
                        # Mapear currency_id
                        if field_name == 'currency_id' and self.currency_mapping:
                            if isinstance(field_value, (int, str)):
                                v13_id_str = str(field_value)
                                if v13_id_str in self.currency_mapping:
                                    field_value = self.currency_mapping[v13_id_str]
                                    logger.debug(f"  [CURRENCY MAP] {field_name} mapeado: v13[{v13_id_str}] -> v18[{field_value}]")
                            elif isinstance(field_value, list) and len(field_value) >= 1:
                                v13_id = field_value[0]
                                if v13_id:
                                    v13_id_str = str(v13_id)
                                    if v13_id_str in self.currency_mapping:
                                        field_value = self.currency_mapping[v13_id_str]
                                        logger.debug(f"  [CURRENCY MAP] {field_name} mapeado desde tupla: v13[{v13_id_str}] -> v18[{field_value}]")
                        
                        # Mapear pricelist_id para sale.subscription
                        elif field_name == 'pricelist_id' and model == 'sale.subscription':
                            # Cargar pricelist_mapping si no está cargado
                            if not self.pricelist_mapping:
                                self.pricelist_mapping = self.v18_conn.get_migration_mapping('product.pricelist')
                                logger.debug(f"  [PRICELIST MAP] Cargado mapeo de product.pricelist: {len(self.pricelist_mapping)} registros")
                            
                            if self.pricelist_mapping:
                                v13_pricelist_id = None
                                if isinstance(field_value, (int, str)):
                                    v13_pricelist_id = field_value
                                elif isinstance(field_value, list) and len(field_value) >= 1:
                                    v13_pricelist_id = field_value[0]
                                
                                if v13_pricelist_id:
                                    v13_id_str = str(v13_pricelist_id)
                                    if v13_id_str in self.pricelist_mapping:
                                        mapped_value = self.pricelist_mapping[v13_id_str]
                                        logger.info(f"  [PRICELIST MAP] ✓ {field_name} mapeado para contrato v13[{record_v13_id}]: v13[{v13_id_str}] -> v18[{mapped_value}]")
                                        # IMPORTANTE: Guardar el valor mapeado directamente en prepared_record y continuar
                                        # para evitar que el procesamiento genérico many2one lo sobrescriba
                                        prepared_record[field_name] = mapped_value
                                        continue  # Saltar el procesamiento genérico many2one
                                    else:
                                        available_ids = sorted(list(self.pricelist_mapping.keys()))[:20]
                                        logger.error(f"  ✗ [PRICELIST MAP] ERROR: {field_name} v13[{v13_id_str}] del contrato v13[{record_v13_id}] NO encontrado en mapeo de product.pricelist ({len(self.pricelist_mapping)} mapeos disponibles). Ejemplos: {available_ids}")
                                        # Si no hay mapeo, NO asignar un valor por defecto
                                        # Dejar que la verificación final lo maneje con un error crítico
                                        # No continuar, dejar que el procesamiento genérico many2one lo maneje
                        
                        # Mapear uom_id y uom_po_id
                        elif field_name in ['uom_id', 'uom_po_id'] and self.uom_mapping:
                            uom_mapping_dict = self.uom_mapping.get('mapping', {})
                            if isinstance(field_value, (int, str)):
                                v13_id_str = str(field_value)
                                if v13_id_str in uom_mapping_dict:
                                    field_value = uom_mapping_dict[v13_id_str]
                                    logger.debug(f"  [UOM MAP] {field_name} mapeado: v13[{v13_id_str}] -> v18[{field_value}]")
                                    
                                    # Registrar cambio de nombre si existe
                                    name_changes = self.uom_mapping.get('name_changes', {})
                                    if v13_id_str in name_changes:
                                        change_info = name_changes[v13_id_str]
                                        logger.info(f"  [UOM NAME CHANGE] {field_name}: \"{change_info['v13_name']}\" -> \"{change_info['v18_name']}\" (v13_id: {v13_id_str}, v18_id: {field_value})")
                                        # Guardar información para registrar en migration.tracking después
                                        if '_uom_name_changes' not in prepared_record:
                                            prepared_record['_uom_name_changes'] = []
                                        prepared_record['_uom_name_changes'].append({
                                            'field': field_name,
                                            'v13_id': int(v13_id_str),
                                            'v18_id': field_value,
                                            'v13_name': change_info['v13_name'],
                                            'v18_name': change_info['v18_name']
                                        })
                            elif isinstance(field_value, list) and len(field_value) >= 1:
                                v13_id = field_value[0]
                                if v13_id:
                                    v13_id_str = str(v13_id)
                                    if v13_id_str in uom_mapping_dict:
                                        field_value = uom_mapping_dict[v13_id_str]
                                        logger.debug(f"  [UOM MAP] {field_name} mapeado desde tupla: v13[{v13_id_str}] -> v18[{field_value}]")
                                        
                                        # Registrar cambio de nombre si existe
                                        name_changes = self.uom_mapping.get('name_changes', {})
                                        if v13_id_str in name_changes:
                                            change_info = name_changes[v13_id_str]
                                            logger.info(f"  [UOM NAME CHANGE] {field_name}: \"{change_info['v13_name']}\" -> \"{change_info['v18_name']}\" (v13_id: {v13_id_str}, v18_id: {field_value})")
                                            # Guardar información para registrar en migration.tracking después
                                            if '_uom_name_changes' not in prepared_record:
                                                prepared_record['_uom_name_changes'] = []
                                        prepared_record['_uom_name_changes'].append({
                                            'field': field_name,
                                            'v13_id': int(v13_id_str),
                                            'v18_id': field_value,
                                            'v13_name': change_info['v13_name'],
                                            'v18_name': change_info['v18_name']
                                        })
                        
                        # Mapear category_id para uom.uom
                        elif field_name == 'category_id' and model == 'uom.uom':
                            # El mapeo ya debería estar actualizado al inicio de _migrate_batches_with_mapping
                            # Solo usamos el mapeo actualizado aquí
                            
                            logger.debug(f"  [UOM CATEGORY MAP] Procesando category_id para {model}. Valor recibido: {field_value} (tipo: {type(field_value)})")
                            
                            if self.uom_category_mapping:
                                logger.debug(f"  [UOM CATEGORY MAP] Mapeo disponible con {len(self.uom_category_mapping)} categorías: {sorted(self.uom_category_mapping.keys())}")
                                
                                if isinstance(field_value, (int, str)):
                                    v13_id_str = str(field_value)
                                    logger.debug(f"  [UOM CATEGORY MAP] category_id es int/str: {v13_id_str}")
                                    if v13_id_str in self.uom_category_mapping:
                                        field_value = self.uom_category_mapping[v13_id_str]
                                        logger.debug(f"  [UOM CATEGORY MAP] {field_name} mapeado: v13[{v13_id_str}] -> v18[{field_value}]")
                                    else:
                                        # Si no hay mapeo, usar categoría por defecto (Unit, ID=1)
                                        logger.error(f"  [UOM CATEGORY MAP] ❌ ERROR: No se encontró mapeo para category_id v13[{v13_id_str}]. Mapeo actual tiene {len(self.uom_category_mapping)} categorías: {sorted(self.uom_category_mapping.keys())}")
                                        field_value = 1
                                        logger.warning(f"  [UOM CATEGORY MAP] ⚠ Usando categoría por defecto: 1 (Unit)")
                                elif isinstance(field_value, list) and len(field_value) >= 1:
                                    v13_id = field_value[0]
                                    logger.debug(f"  [UOM CATEGORY MAP] category_id es lista. Extraído v13_id: {v13_id} (tipo: {type(v13_id)})")
                                    if v13_id:
                                        v13_id_str = str(v13_id)
                                        logger.debug(f"  [UOM CATEGORY MAP] Buscando mapeo para v13_id: {v13_id_str}")
                                        if v13_id_str in self.uom_category_mapping:
                                            field_value = self.uom_category_mapping[v13_id_str]
                                            logger.info(f"  [UOM CATEGORY MAP] ✓ {field_name} mapeado desde tupla: v13[{v13_id_str}] -> v18[{field_value}]")
                                        else:
                                            # Si no hay mapeo, usar categoría por defecto (Unit, ID=1)
                                            logger.error(f"  [UOM CATEGORY MAP] ❌ ERROR: No se encontró mapeo para category_id v13[{v13_id_str}]. Mapeo actual tiene {len(self.uom_category_mapping)} categorías: {sorted(self.uom_category_mapping.keys())}")
                                            field_value = 1
                                            logger.warning(f"  [UOM CATEGORY MAP] ⚠ Usando categoría por defecto: 1 (Unit)")
                                    else:
                                        # Si el valor es False/None, usar categoría por defecto
                                        field_value = 1
                                        logger.warning(f"  [UOM CATEGORY MAP] ⚠ category_id es False/None, usando categoría por defecto: 1 (Unit)")
                                elif field_value is False or field_value is None:
                                    # Si el valor es False/None, usar categoría por defecto
                                    field_value = 1
                                    logger.warning(f"  [UOM CATEGORY MAP] ⚠ category_id es False/None, usando categoría por defecto: 1 (Unit)")
                            else:
                                # Si no hay mapeo disponible, usar categoría por defecto
                                field_value = 1
                                logger.warning(f"  [UOM CATEGORY MAP] ⚠ No hay mapeo de categorías disponible, usando categoría por defecto: 1 (Unit)")
                    
                    # IMPORTANTE: Si el campo ya fue procesado y guardado en prepared_record (ej: pricelist_id mapeado),
                    # NO procesarlo de nuevo, preservar el valor ya guardado
                    if field_name in prepared_record:
                        # Log de depuración para pricelist_id
                        if field_name == 'pricelist_id' and model == 'sale.subscription':
                            logger.debug(f"  [SKIP] Campo {field_name} ya está en prepared_record con valor: {prepared_record[field_name]} (tipo: {type(prepared_record[field_name])})")
                        continue  # El campo ya fue procesado, continuar con el siguiente
                    
                    # IMPORTANTE: Si el campo es many2one y ya tiene un valor entero (ya fue mapeado),
                    # NO procesarlo de nuevo, preservar el valor mapeado
                    field_info_check = v18_fields.get(field_name, {})
                    if field_info_check.get('type') == 'many2one':
                        # Si el valor ya es un entero (fue mapeado), preservarlo
                        if isinstance(field_value, int):
                            prepared_record[field_name] = field_value
                            continue  # Ya está mapeado, no procesar más
                        # Si es False (fue establecido a False porque no había mapeo), preservarlo
                        elif field_value is False:
                            prepared_record[field_name] = False
                            continue  # Ya está establecido a False, no procesar más
                        # Si es una lista/tupla [id, name], extraer solo el ID
                        # (pero esto no debería pasar si ya fue mapeado)
                        elif isinstance(field_value, (list, tuple)) and len(field_value) > 0:
                            # CRÍTICO: Si user_id en res.partner viene como lista pero no está mapeado,
                            # establecer False para evitar errores de foreign key
                            if field_name == 'user_id' and model == 'res.partner':
                                logger.warning(f"  ⚠ CRÍTICO: Campo user_id en res.partner viene como lista [{field_value[0]}, ...] pero no está mapeado, estableciendo False para evitar error de foreign key")
                                prepared_record[field_name] = False
                                continue
                            # Si el primer elemento es un entero, usarlo (pero debería estar mapeado)
                            if isinstance(field_value[0], int):
                                logger.warning(f"  ⚠ Campo many2one {field_name} viene como lista pero debería estar mapeado, usando ID: {field_value[0]}")
                                field_value = field_value[0]
                            else:
                                field_value = False
                        elif field_value is None:
                            field_value = False
                        else:
                            # Valor desconocido, establecer False para evitar errores
                            logger.warning(f"  ⚠ Campo many2one {field_name} tiene formato desconocido: {type(field_value)}, estableciendo False")
                            if field_name == 'user_id' and model == 'res.partner':
                                prepared_record[field_name] = False
                                continue
                            else:
                                continue
                    
                    # Incluir el campo solo si tiene un valor válido
                    # Asegurar que el valor sea serializable (no objetos complejos)
                    if isinstance(field_value, (dict, list)) and not isinstance(field_value, (str, int, float, bool, type(None))):
                        # Si es un diccionario o lista compleja, convertir a formato válido
                        # Para otros tipos (no many2one), omitir si no es serializable
                        logger.warning(f"  ⚠ Campo {field_name} tiene valor no serializable: {type(field_value)}, omitiendo")
                        continue
                    
                    # Verificar que el valor sea de un tipo válido para Odoo
                    if not isinstance(field_value, (str, int, float, bool, type(None))):
                        logger.warning(f"  ⚠ Campo {field_name} tiene tipo inválido: {type(field_value)}, omitiendo")
                        continue
                    
                    # Incluir el campo
                    prepared_record[field_name] = field_value
                
                # Mapeo especial después de procesar todos los campos:
                # quantity en contract.line se mapea a product_uom_qty en sale.subscription.line
                if model == 'sale.subscription.line' and 'quantity' in record:
                    prepared_record['product_uom_qty'] = record['quantity']
                    # Eliminar quantity ya que no existe en v18
                    if 'quantity' in prepared_record:
                        del prepared_record['quantity']
                    logger.debug(f"  [MAPEO CAMPO POST] quantity mapeado a product_uom_qty: {record['quantity']}")
                
                # specific_price en contract.line se mapea a price_unit en sale.subscription.line
                if model == 'sale.subscription.line' and 'specific_price' in record:
                    specific_price = record.get('specific_price')
                    if specific_price is not None and specific_price is not False:
                        prepared_record['price_unit'] = specific_price
                        logger.debug(f"  [MAPEO CAMPO POST] specific_price mapeado a price_unit: {specific_price}")
                    # Eliminar specific_price ya que no existe en v18
                    if 'specific_price' in prepared_record:
                        del prepared_record['specific_price']
                
                # Asegurar que campos requeridos tengan valores válidos (verificación final)
                
                # Asegurar que campos requeridos tengan valores válidos (verificación final)
                # IMPORTANTE: Excluir campos con store=False (computed) incluso si son requeridos
                for required_field in required_fields:
                    # EXCLUIR campos sin store (computed) - no se pueden establecer en create()
                    if required_field in no_store_fields:
                        continue  # Saltar campos computed sin store
                    
                    # Verificar si el campo está presente y tiene un valor válido
                    field_value = prepared_record.get(required_field)
                    field_info = v18_fields.get(required_field, {})
                    field_type = field_info.get('type', '')
                    
                    # Verificar si el valor es None, False, o cadena vacía
                    is_empty = (required_field not in prepared_record or 
                               field_value is None or 
                               field_value is False or 
                               (isinstance(field_value, str) and not field_value.strip()))
                    
                    # Log de depuración para pricelist_id
                    if required_field == 'pricelist_id' and model == 'sale.subscription':
                        logger.debug(f"  [DEBUG PRICELIST] Verificando {required_field} en {model} (contrato v13[{record_v13_id}]): en prepared_record={required_field in prepared_record}, valor={field_value}, is_empty={is_empty}")
                    
                    # Caso especial: company_id requerido en res.users
                    # (res.company no está en models_to_migrate.txt, pero company_id es requerido en v18)
                    if is_empty and required_field == 'company_id' and model == 'res.users':
                        # Buscar la compañía principal
                        try:
                            company_domain = []
                            companies = self.v18_conn.search_read('res.company', company_domain, ['id'], limit=1)
                            if companies:
                                prepared_record[required_field] = companies[0]['id']
                                logger.debug(f"  [VERIFICACIÓN FINAL] Campo requerido {required_field} en {model} sin valor (res.company no migrado), asignada compañía por defecto: {prepared_record[required_field]}")
                            else:
                                logger.warning(f"  ⚠ [VERIFICACIÓN FINAL] No se encontró compañía por defecto para {required_field} en {model}")
                        except Exception as e:
                            logger.warning(f"  ⚠ [VERIFICACIÓN FINAL] Error buscando compañía por defecto para {required_field} en {model}: {e}")
                        continue  # Continuar con el siguiente campo
                    
                    # Caso especial: uom_id requerido en product.template y product.product
                    # (Unidad de medida por defecto: ID=1 'Units')
                    if is_empty and required_field == 'uom_id' and model in ['product.template', 'product.product']:
                        prepared_record[required_field] = 1
                        logger.debug(f"  [VERIFICACIÓN FINAL] Campo requerido {required_field} en {model} sin valor, asignada unidad por defecto: 1 (Units)")
                        continue  # Continuar con el siguiente campo
                    
                    # Caso especial: category_id requerido en uom.uom
                    # (Categoría por defecto: ID=1 'Unit')
                    if is_empty and required_field == 'category_id' and model == 'uom.uom':
                        prepared_record[required_field] = 1
                        logger.debug(f"  [VERIFICACIÓN FINAL] Campo requerido {required_field} en {model} sin valor, asignada categoría por defecto: 1 (Unit)")
                        continue  # Continuar con el siguiente campo
                    
                    # Caso especial: partner_id requerido en sale.subscription
                    # Se mapea desde v13 usando partner_mapping (debe estar mapeado antes)
                    if is_empty and required_field == 'partner_id' and model == 'sale.subscription':
                        v13_partner_id = record.get('partner_id', False)
                        
                        # Extraer el ID de la tupla si viene como lista
                        if isinstance(v13_partner_id, list) and len(v13_partner_id) >= 1:
                            v13_partner_id = v13_partner_id[0]
                        
                        if not v13_partner_id:
                            logger.error(f"  ✗ [VERIFICACIÓN FINAL] ERROR CRÍTICO: partner_id requerido en sale.subscription (contrato v13[{record_v13_id}]) está vacío en el registro v13.")
                            continue
                        
                        # Cargar partner_mapping desde migration.tracking
                        partner_mapping = self.v18_conn.get_migration_mapping('res.partner')
                        if not partner_mapping:
                            logger.error(f"  ✗ [VERIFICACIÓN FINAL] ERROR CRÍTICO: No se pudo cargar el mapeo de res.partner desde migration.tracking.")
                            continue
                        
                        v13_id_str = str(v13_partner_id)
                        if v13_id_str in partner_mapping:
                            prepared_record[required_field] = partner_mapping[v13_id_str]
                            logger.info(f"  [VERIFICACIÓN FINAL] ✓ Campo requerido {required_field} en {model} (contrato v13[{record_v13_id}]) mapeado desde v13: {v13_id_str} -> {prepared_record[required_field]}")
                            continue
                        else:
                            logger.error(f"  ✗ [VERIFICACIÓN FINAL] ERROR CRÍTICO: partner_id v13[{v13_id_str}] del contrato v13[{record_v13_id}] NO está mapeado en res.partner. Mapeos disponibles: {len(partner_mapping)}.")
                            continue
                    
                    # Caso especial: company_id requerido en sale.subscription
                    # Se mapea desde v13 usando company_mapping o se usa compañía por defecto
                    if is_empty and required_field == 'company_id' and model == 'sale.subscription':
                        v13_company_id = record.get('company_id', False)
                        
                        # Extraer el ID de la tupla si viene como lista
                        if isinstance(v13_company_id, list) and len(v13_company_id) >= 1:
                            v13_company_id = v13_company_id[0]
                        
                        # Intentar mapear desde v13 si existe
                        if v13_company_id:
                            company_mapping = self.v18_conn.get_migration_mapping('res.company')
                            if company_mapping:
                                v13_id_str = str(v13_company_id)
                                if v13_id_str in company_mapping:
                                    prepared_record[required_field] = company_mapping[v13_id_str]
                                    logger.info(f"  [VERIFICACIÓN FINAL] ✓ Campo requerido {required_field} en {model} (contrato v13[{record_v13_id}]) mapeado desde v13: {v13_id_str} -> {prepared_record[required_field]}")
                                    continue
                        
                        # Si no hay mapeo o no hay company_id en v13, usar compañía por defecto
                        logger.warning(f"  ⚠ [VERIFICACIÓN FINAL] company_id requerido en sale.subscription (contrato v13[{record_v13_id}]) sin mapeo. Usando compañía por defecto.")
                        try:
                            companies = self.v18_conn.search_read('res.company', [], ['id'], limit=1, order='id asc')
                            if companies:
                                prepared_record[required_field] = companies[0]['id']
                                logger.info(f"  [VERIFICACIÓN FINAL] ✓ Campo requerido {required_field} en {model} (contrato v13[{record_v13_id}]) asignado compañía por defecto: {prepared_record[required_field]}")
                                continue
                            else:
                                logger.error(f"  ✗ [VERIFICACIÓN FINAL] ERROR CRÍTICO: No se encontró ninguna compañía para {required_field} en {model}")
                                continue
                        except Exception as e:
                            logger.error(f"  ✗ [VERIFICACIÓN FINAL] ERROR CRÍTICO: Error buscando compañía por defecto para {required_field} en {model}: {e}")
                            continue
                    
                    # Caso especial: template_id requerido en sale.subscription
                    # Se determina basándose en recurring_rule_type y recurring_interval del contrato v13
                    if is_empty and required_field == 'template_id' and model == 'sale.subscription':
                        recurring_rule_type = record.get('recurring_rule_type', '')
                        recurring_interval = record.get('recurring_interval', 1)
                        template_id = self.get_template_id_for_contract(recurring_rule_type, recurring_interval)
                        prepared_record[required_field] = template_id
                        logger.debug(f"  [VERIFICACIÓN FINAL] Campo requerido {required_field} en {model} determinado por recurrencia: rule_type={recurring_rule_type}, interval={recurring_interval} -> template_id={template_id}")
                        continue  # Continuar con el siguiente campo
                    
                    # Caso especial: pricelist_id requerido en sale.subscription
                    # Se mapea desde v13 usando pricelist_mapping (ya debería estar mapeado antes)
                    # Esta verificación solo aplica si todavía está vacío después del mapeo
                    if is_empty and required_field == 'pricelist_id' and model == 'sale.subscription':
                        # Verificar si ya se mapeó en la sección anterior (no debería estar vacío)
                        # Si está vacío, intentar obtenerlo del registro v13 original
                        v13_pricelist_id = record.get('pricelist_id', False)
                        
                        # Extraer el ID de la tupla si viene como lista
                        if isinstance(v13_pricelist_id, list) and len(v13_pricelist_id) >= 1:
                            v13_pricelist_id = v13_pricelist_id[0]
                        
                        # Si el contrato no tiene pricelist_id, usar el pricelist por defecto
                        # NOTA: Esto es aceptable si los precios de las líneas (subscription.line) en v13 
                        # coinciden con los precios de los productos en v18. El usuario debe verificar esto manualmente.
                        if not v13_pricelist_id:
                            logger.warning(f"  ⚠ [VERIFICACIÓN FINAL] Contrato v13[{record_v13_id}] no tiene pricelist_id asignado. Usando pricelist por defecto. NOTA: Verificar que los precios de las líneas (subscription.line) en v13 coincidan con los precios de los productos en v18.")
                            try:
                                # Buscar pricelist por defecto (generalmente es el primero o uno con nombre específico)
                                pricelists = self.v18_conn.search_read('product.pricelist', [], ['id', 'name'], limit=1, order='id asc')
                                if pricelists:
                                    prepared_record[required_field] = pricelists[0]['id']
                                    logger.info(f"  [VERIFICACIÓN FINAL] ✓ Campo requerido {required_field} en {model} (contrato v13[{record_v13_id}]) asignado pricelist por defecto: {prepared_record[required_field]} ({pricelists[0].get('name', 'N/A')})")
                                    continue
                                else:
                                    logger.error(f"  ✗ [VERIFICACIÓN FINAL] ERROR CRÍTICO: No se encontró ningún pricelist para {required_field} en {model}")
                                    continue
                            except Exception as e:
                                logger.error(f"  ✗ [VERIFICACIÓN FINAL] ERROR CRÍTICO: Error buscando pricelist por defecto para {required_field} en {model}: {e}")
                                continue
                        
                        # Cargar pricelist_mapping si no está cargado
                        if not self.pricelist_mapping:
                            self.pricelist_mapping = self.v18_conn.get_migration_mapping('product.pricelist')
                            logger.info(f"  [VERIFICACIÓN FINAL] Cargado mapeo de product.pricelist: {len(self.pricelist_mapping)} registros")
                        
                        if not self.pricelist_mapping:
                            logger.error(f"  ✗ [VERIFICACIÓN FINAL] ERROR CRÍTICO: No se pudo cargar el mapeo de product.pricelist desde migration.tracking. Debe migrarse primero product.pricelist.")
                            # NO asignar un valor por defecto, dejar que falle la creación
                            continue
                        
                        v13_id_str = str(v13_pricelist_id)
                        if v13_id_str in self.pricelist_mapping:
                            prepared_record[required_field] = self.pricelist_mapping[v13_id_str]
                            logger.info(f"  [VERIFICACIÓN FINAL] ✓ Campo requerido {required_field} en {model} (contrato v13[{record_v13_id}]) mapeado desde v13: {v13_id_str} -> {prepared_record[required_field]}")
                            continue
                        else:
                            # CRÍTICO: Si el pricelist_id de v13 no está mapeado, NO usar un valor por defecto
                            # Debe ser el mismo pricelist que viene de contract.contract
                            available_ids = sorted(list(self.pricelist_mapping.keys()))[:20]
                            logger.error(f"  ✗ [VERIFICACIÓN FINAL] ERROR CRÍTICO: pricelist_id v13[{v13_id_str}] del contrato v13[{record_v13_id}] NO está mapeado en product.pricelist. Mapeos disponibles: {len(self.pricelist_mapping)}. Ejemplos: {available_ids}. Debe migrarse primero product.pricelist o verificar que el pricelist_id v13[{v13_id_str}] exista en v18.")
                            # NO asignar un valor por defecto, dejar que falle la creación para que el error sea visible
                            continue
                    
                    # Si el campo no está presente o está null/vacío, asignar valor por defecto
                    if is_empty:
                        # Asignar valor por defecto según el tipo
                        if required_field == 'name':
                            record_id = record.get('id', 'Unknown')
                            if model == 'res.partner':
                                # Intentar usar display_name como fallback
                                display_name = record.get('display_name')
                                
                                if display_name and isinstance(display_name, str) and display_name.strip():
                                    prepared_record[required_field] = display_name
                                else:
                                    # Para res.partner, usar espacio en blanco si no hay nombre
                                    prepared_record[required_field] = " "
                            else:
                                prepared_record[required_field] = f"{model} {record_id}"
                            logger.warning(f"  ⚠ Campo requerido '{required_field}' vacío en {model} (ID: {record_id}), asignado valor por defecto: {prepared_record[required_field]}")
                        elif field_type == 'many2one':
                            prepared_record[required_field] = False
                        elif field_type in ['integer', 'float']:
                            prepared_record[required_field] = 0
                        elif field_type == 'boolean':
                            prepared_record[required_field] = False
                        elif field_type in ['char', 'text']:
                            # Para campos de texto requeridos, usar valor por defecto
                            if required_field == 'name':
                                record_id = record.get('id', 'Unknown')
                                prepared_record[required_field] = f"{model} {record_id}"
                            else:
                                prepared_record[required_field] = ""
                        # Para otros tipos, se omiten (pueden causar errores)
                
                # Verificación final crítica: asegurar que 'name' siempre tenga un valor válido
                if 'name' in required_fields:
                    final_name = prepared_record.get('name')
                    if not final_name or (isinstance(final_name, str) and not final_name.strip()):
                        record_id = record.get('id', 'Unknown')
                        if model == 'res.partner':
                            # Para res.partner, usar espacio en blanco si no hay nombre
                            prepared_record['name'] = " "
                        else:
                            prepared_record['name'] = f"{model} {record_id}"
                        logger.error(f"  ✗ ERROR CRÍTICO: Campo 'name' quedó vacío después de todo el procesamiento en {model} (ID: {record_id}), forzando valor: {prepared_record['name']}")
                
                # VERIFICACIÓN FINAL CRÍTICA: user_id en res.partner debe ser False si no está mapeado correctamente
                # Esto evita errores de foreign key constraint
                if model == 'res.partner' and 'user_id' in prepared_record:
                    user_id_value = prepared_record.get('user_id')
                    # Si user_id no es False y no es un entero válido, establecerlo a False
                    if user_id_value is not False and user_id_value is not None:
                        # Verificar si es un entero válido (ya mapeado)
                        if isinstance(user_id_value, int) and user_id_value > 0:
                            # Es un ID válido, mantenerlo
                            pass
                        elif isinstance(user_id_value, (list, tuple)) and len(user_id_value) > 0:
                            # Viene como lista [id, name], pero no debería llegar aquí si ya fue mapeado
                            # Establecer a False para evitar error
                            logger.warning(f"  ⚠ [VERIFICACIÓN FINAL] user_id en res.partner viene como lista {user_id_value}, estableciendo False para evitar error de foreign key")
                            prepared_record['user_id'] = False
                        else:
                            # Cualquier otro valor, establecer a False
                            logger.warning(f"  ⚠ [VERIFICACIÓN FINAL] user_id en res.partner tiene valor inválido {user_id_value} (tipo: {type(user_id_value)}), estableciendo False")
                            prepared_record['user_id'] = False
                    elif user_id_value is None:
                        # None no es válido, establecer a False
                        prepared_record['user_id'] = False
                
                # Guardar el registro preparado junto con sus campos many2many
                # Asegurar que campos nuevos requeridos en v18 se agreguen automáticamente
                # para modelos de productos
                if model in ['product.template', 'product.product']:
                    # Campos nuevos requeridos en v18
                    if 'service_tracking' not in prepared_record:
                        prepared_record['service_tracking'] = 'no'
                        logger.debug(f"  [DEFAULT] Agregado campo requerido service_tracking='no' para {model}")
                    if 'purchase_line_warn' not in prepared_record:
                        prepared_record['purchase_line_warn'] = 'no-message'
                        logger.debug(f"  [DEFAULT] Agregado campo requerido purchase_line_warn='no-message' para {model}")
                    if 'ticket_active' not in prepared_record:
                        prepared_record['ticket_active'] = False
                        logger.debug(f"  [DEFAULT] Agregado campo requerido ticket_active=False para {model}")
                    
                    # uom_id es requerido en v18 - asignar unidad por defecto si falta o es False/None
                    uom_id_value = prepared_record.get('uom_id')
                    if not uom_id_value or uom_id_value is False:
                        # Unidad de medida por defecto: ID=1 ('Units')
                        prepared_record['uom_id'] = 1
                        logger.debug(f"  [DEFAULT] Agregado campo requerido uom_id=1 (Units) para {model} (valor original: {uom_id_value})")
                    
                    # uom_po_id también puede necesitar valor por defecto si falta
                    uom_po_id_value = prepared_record.get('uom_po_id')
                    if not uom_po_id_value or uom_po_id_value is False:
                        # Usar la misma unidad que uom_id
                        prepared_record['uom_po_id'] = prepared_record.get('uom_id', 1)
                        logger.debug(f"  [DEFAULT] Agregado campo uom_po_id={prepared_record['uom_po_id']} (mismo que uom_id) para {model}")
                
                elif model == 'product.pricelist.item':
                    # Campo nuevo requerido en v18: display_applied_on
                    if 'display_applied_on' not in prepared_record:
                        # Mapear desde applied_on
                        applied_on = prepared_record.get('applied_on', record.get('applied_on', ''))
                        if applied_on == '1_product':
                            display_applied_on = '1_product'
                        elif applied_on == '2_product_category':
                            display_applied_on = '2_product_category'
                        elif applied_on == '0_product_variant':
                            display_applied_on = '1_product'  # Product variant -> Product
                        elif applied_on == '3_global':
                            display_applied_on = '1_product'  # Global -> Product (por defecto)
                        else:
                            display_applied_on = '1_product'  # Valor por defecto
                        prepared_record['display_applied_on'] = display_applied_on
                        logger.debug(f"  [DEFAULT] Agregado campo requerido display_applied_on='{display_applied_on}' (desde applied_on='{applied_on}') para {model}")
                
                # Caso especial: Calcular stage_id para sale.subscription basándose en condiciones
                if model == 'sale.subscription':
                    from datetime import datetime, date
                    
                    # Verificar que stage_id esté en los campos válidos
                    if 'stage_id' not in valid_field_names:
                        logger.warning(f"  [ESTADO] Campo 'stage_id' no encontrado en campos válidos de sale.subscription, estableciendo In progress (ID=3) por defecto")
                        prepared_record['stage_id'] = 3
                    else:
                        # Obtener valores de date_end y recurring_next_date
                        date_end = prepared_record.get('date_end') or record.get('date_end')
                        recurring_next_date = prepared_record.get('recurring_next_date') or record.get('recurring_next_date')
                        
                        # Inicializar stage_id con valor por defecto (In progress = 3)
                        stage_id = 3
                        stage_name = 'In progress'
                        
                        # Convertir date_end a objeto date si es string
                        if isinstance(date_end, str):
                            try:
                                date_end = datetime.strptime(date_end, '%Y-%m-%d').date()
                            except:
                                try:
                                    date_end = datetime.strptime(date_end.split(' ')[0], '%Y-%m-%d').date()
                                except:
                                    date_end = None
                        elif date_end:
                            # Si es datetime, convertir a date
                            if isinstance(date_end, datetime):
                                date_end = date_end.date()
                        
                        # Convertir recurring_next_date a objeto date si es string
                        # IMPORTANTE: Verificar si es False o string vacío ANTES de convertir
                        if recurring_next_date is False or recurring_next_date is None:
                            recurring_next_date = False
                        elif isinstance(recurring_next_date, str):
                            # Si es string vacío, tratarlo como False
                            if not recurring_next_date.strip():
                                recurring_next_date = False
                            else:
                                try:
                                    recurring_next_date = datetime.strptime(recurring_next_date, '%Y-%m-%d').date()
                                except:
                                    try:
                                        recurring_next_date = datetime.strptime(recurring_next_date.split(' ')[0], '%Y-%m-%d').date()
                                    except:
                                        recurring_next_date = False
                        elif recurring_next_date:
                            # Si es datetime, convertir a date
                            if isinstance(recurring_next_date, datetime):
                                recurring_next_date = recurring_next_date.date()
                        else:
                            recurring_next_date = False
                        
                        # Obtener fecha actual
                        today = date.today()
                        
                        # Calcular stage_id según las condiciones:
                        # "In progress": date_end >= hoy O (date_end == False Y recurring_next_date != False)
                        # "Closed": date_end < hoy Y recurring_next_date == False
                        try:
                            if date_end is None or date_end is False:
                                # date_end es False o None
                                if recurring_next_date and recurring_next_date is not False:
                                    # date_end == False Y recurring_next_date != False -> In progress (ID=3)
                                    stage_id = 3
                                    stage_name = 'In progress'
                                else:
                                    # Si no hay recurring_next_date, usar Closed (ID=4)
                                    stage_id = 4
                                    stage_name = 'Closed'
                            else:
                                # date_end tiene valor
                                if date_end >= today:
                                    # date_end >= hoy -> In progress (ID=3)
                                    stage_id = 3
                                    stage_name = 'In progress'
                                else:
                                    # date_end < hoy
                                    if recurring_next_date is None or recurring_next_date is False:
                                        # date_end < hoy Y recurring_next_date == False -> Closed (ID=4)
                                        stage_id = 4
                                        stage_name = 'Closed'
                                    else:
                                        # date_end < hoy pero recurring_next_date != False -> In progress (ID=3)
                                        stage_id = 3
                                        stage_name = 'In progress'
                        except Exception as e:
                            logger.warning(f"  [ESTADO] Error calculando stage_id para sale.subscription (ID v13: {record_v13_id}): {e}, usando In progress (ID=3) por defecto")
                            stage_id = 3
                            stage_name = 'In progress'
                        
                        # IMPORTANTE: Agregar stage_id directamente al prepared_record
                        # Esto se hace DESPUÉS de procesar todos los campos del registro original
                        prepared_record['stage_id'] = stage_id
                        logger.info(f"  [ESTADO] ✓ stage_id establecido para sale.subscription (ID v13: {record_v13_id}): {stage_id} ({stage_name}) (date_end={date_end}, recurring_next_date={recurring_next_date}, hoy={today})")
                
                # Asegurar que stage_id esté establecido para sale.subscription ANTES de agregar a prepared_records
                if model == 'sale.subscription' and 'stage_id' not in prepared_record:
                    # Si por alguna razón no se estableció, usar In progress (ID=3) como defecto
                    prepared_record['stage_id'] = 3
                    logger.warning(f"  [ESTADO] ⚠ stage_id no estaba establecido para sale.subscription (ID v13: {record_v13_id}), estableciendo In progress (ID=3) como defecto")
                
                # Agregar prefijo "OLDV13:" al nombre de productos (product.template y product.product)
                if model in ['product.template', 'product.product'] and 'name' in prepared_record:
                    current_name = prepared_record['name']
                    if current_name and isinstance(current_name, str) and not current_name.startswith('OLDV13:'):
                        prepared_record['name'] = f"OLDV13: {current_name}"
                        logger.debug(f"  [PREFIJO] Agregado prefijo 'OLDV13:' al nombre de {model} (ID v13: {record_v13_id}): '{current_name}' -> '{prepared_record['name']}'")
                
                # Agregar etiqueta "OLDv13" a productos (product.template y product.product)
                if model in ['product.template', 'product.product']:
                    # Obtener o crear la etiqueta "OLDv13" si no está cargada
                    if self.oldv13_tag_id is None:
                        self.oldv13_tag_id = self.get_or_create_oldv13_tag()
                    
                    if self.oldv13_tag_id:
                        # Agregar la etiqueta a product_tag_ids usando m2m_fields
                        if 'product_tag_ids' not in m2m_fields:
                            m2m_fields['product_tag_ids'] = []
                        
                        # Agregar el ID de la etiqueta si no está ya presente
                        if self.oldv13_tag_id not in m2m_fields['product_tag_ids']:
                            m2m_fields['product_tag_ids'].append(self.oldv13_tag_id)
                            logger.debug(f"  [ETIQUETA] Agregada etiqueta 'OLDv13' (ID: {self.oldv13_tag_id}) a {model} (ID v13: {record_v13_id})")
                    else:
                        logger.warning(f"  [ETIQUETA] ⚠ No se pudo obtener/crear etiqueta 'OLDv13' para {model} (ID v13: {record_v13_id})")
                
                prepared_records.append({
                    'record': prepared_record,
                    'm2m_fields': m2m_fields,
                    'v13_id': record.get('id')
                })
            
            # Log resumido de campos removidos si hay alguno
            if removed_fields_count:
                total_removed_fields = len(removed_fields_count)
                logger.info(f"[PREPARACIÓN] {total_removed_fields} campos removidos de {model} (no existen en v18 o son readonly/computed)")
            
            return prepared_records
            
        except Exception as e:
            logger.warning(f"⚠ Error preparando registros para {model}: {e}")
            logger.warning("⚠ Usando registros sin validación (puede causar errores)")
            # En caso de error, retornar registros con limpieza básica
            system_fields = {'id', 'create_uid', 'write_uid', 'create_date', 'write_date'}
            prepared_records = []
            for record in records:
                prepared_record = {k: v for k, v in record.items() 
                                 if k not in system_fields and v is not None}
                prepared_records.append(prepared_record)
            return prepared_records
    
    def _register_uom_name_changes(self, uom_name_changes: List[Dict], batch_id: str = None):
        """
        Registra cambios de nombre de unidades de medida en migration.tracking.
        
        Args:
            uom_name_changes: Lista de diccionarios con información de cambios de nombre
            batch_id: ID del batch (opcional)
        """
        if not uom_name_changes:
            return
        
        try:
            tracking_data = []
            for change in uom_name_changes:
                tracking_data.append({
                    'name': f"uom.uom - V13:{change['v13_id']} \"{change['v13_name']}\" -> V18:{change['v18_id']} \"{change['v18_name']}\" (CAMBIÓ DE NOMBRE)",
                    'model_name': 'uom.uom',
                    'v13_id': change['v13_id'],
                    'v18_id': change['v18_id'],
                    'batch_id': batch_id or f"uom_name_change_{change['v13_id']}",
                    'status': 'created',
                    'error_message': f"Unidad cambió de nombre: \"{change['v13_name']}\" -> \"{change['v18_name']}\" (usado en campo {change.get('field', 'N/A')} del modelo {change.get('model_v13_id', 'N/A')})"
                })
            
            if tracking_data:
                logger.info(f"[UOM NAME CHANGE] Registrando {len(tracking_data)} cambios de nombre de unidades en migration.tracking...")
                self.v18_conn.models.execute_kw(
                    self.v18_conn.db, self.v18_conn.uid, self.v18_conn.password,
                    'migration.tracking', 'create',
                    [tracking_data]
                )
                logger.info(f"[UOM NAME CHANGE] ✓ {len(tracking_data)} cambios de nombre registrados en migration.tracking")
        except Exception as e:
            logger.warning(f"[UOM NAME CHANGE] ⚠ Error registrando cambios de nombre en migration.tracking: {e}")
    
    def map_parent_id(self, records: List[Dict], model: str) -> List[Dict]:
        """
        Mapea parent_id de v13 a v18 usando migration.tracking.
        En modo test, simula el mapeo usando los IDs v13 como si fueran v18.
        
        Args:
            records: Lista de registros a mapear
            model: Nombre del modelo (el mismo modelo, parent_id apunta al mismo modelo)
        
        Returns:
            Lista de registros con parent_id mapeado
        """
        if self.test_mode:
            # En modo test, simular mapeo: usar el mismo ID v13 como si fuera v18
            logger.info("  [MODO TEST] Simulando mapeo de parent_id (usando IDs v13 como v18)")
            mapped_records = []
            mapped_count = 0
            
            for record in records:
                mapped_record = record.copy()
                
                if 'parent_id' in mapped_record:
                    v13_parent_id = mapped_record['parent_id']
                    
                    # parent_id viene como [id, name] en search_read de Odoo
                    if v13_parent_id and isinstance(v13_parent_id, (list, tuple)) and len(v13_parent_id) > 0:
                        v13_parent_id_value = v13_parent_id[0]
                        # En modo test, usar el mismo ID como si fuera v18
                        mapped_record['parent_id'] = v13_parent_id_value
                        mapped_count += 1
                    elif v13_parent_id and isinstance(v13_parent_id, (int, str)):
                        v13_parent_id_value = int(v13_parent_id) if isinstance(v13_parent_id, str) else v13_parent_id
                        mapped_record['parent_id'] = v13_parent_id_value
                        mapped_count += 1
                
                mapped_records.append(mapped_record)
            
            if mapped_count > 0:
                logger.info(f"  [MODO TEST] ✓ Simulados {mapped_count} campos parent_id")
            
            return mapped_records
        
        # Obtener mapeo del mismo modelo (parent_id apunta al mismo modelo)
        mapping = self.v18_conn.get_migration_mapping(model)
        
        if not mapping:
            logger.warning(f"  ⚠ No se encontró mapeo para {model}, no se mapeará parent_id")
            return records
        
        logger.info(f"  Mapeo cargado para parent_id -> {model}: {len(mapping)} registros")
        
        # Mapear parent_id en los registros
        mapped_records = []
        mapped_count = 0
        not_mapped_count = 0
        
        for record in records:
            mapped_record = record.copy()
            
            if 'parent_id' in mapped_record:
                v13_parent_id = mapped_record['parent_id']
                v13_parent_id_value = None
                
                # parent_id puede venir en diferentes formatos:
                # 1. Como tupla [id, name] desde search_read de Odoo
                # 2. Como array simple [id] desde JSON
                # 3. Como número directo desde JSON
                # 4. Como False o None (sin parent)
                
                if v13_parent_id and isinstance(v13_parent_id, (list, tuple)) and len(v13_parent_id) > 0:
                    # Es una lista/tupla, tomar el primer elemento (el ID)
                    v13_parent_id_value = v13_parent_id[0]
                elif v13_parent_id and isinstance(v13_parent_id, (int, str)):
                    # Es un número o string directo
                    v13_parent_id_value = int(v13_parent_id) if isinstance(v13_parent_id, str) else v13_parent_id
                elif v13_parent_id is False or v13_parent_id is None:
                    # Sin parent, mantener False
                    mapped_records.append(mapped_record)
                    continue
                else:
                    # Formato desconocido, mantener como está
                    logger.debug(f"  Formato desconocido para parent_id: {type(v13_parent_id)} = {v13_parent_id}")
                    mapped_records.append(mapped_record)
                    continue
                
                # Mapear el ID de v13 a v18
                if v13_parent_id_value is not None:
                    v13_parent_id_str = str(v13_parent_id_value)
                    if v13_parent_id_str in mapping:
                        v18_parent_id = mapping[v13_parent_id_str]
                        mapped_record['parent_id'] = v18_parent_id
                        mapped_count += 1
                        logger.debug(f"  Mapeado parent_id: {v13_parent_id_value} (v13) -> {v18_parent_id} (v18)")
                    else:
                        # Si no hay mapeo, poner False (sin parent) y registrar
                        logger.warning(f"  ⚠ No se encontró mapeo para parent_id={v13_parent_id_value} en {model} (v13_id no migrado aún)")
                        mapped_record['parent_id'] = False
                        not_mapped_count += 1
                else:
                    # No se pudo extraer el ID, mantener False
                    mapped_record['parent_id'] = False
                    logger.debug(f"  No se pudo extraer ID de parent_id: {v13_parent_id}")
            else:
                # No hay parent_id en el registro, mantener como está
                pass
            
            mapped_records.append(mapped_record)
        
        if mapped_count > 0:
            logger.info(f"  ✓ Mapeados {mapped_count} campos parent_id")
        if not_mapped_count > 0:
            logger.warning(f"  ⚠ {not_mapped_count} campos parent_id no pudieron mapearse (el padre no está migrado aún, se crearán sin parent)")
        
        return mapped_records
    
    def map_many2one_ids(self, records: List[Dict], model: str, 
                        models_list: List[str]) -> List[Dict]:
        """
        Mapea IDs de campos many2one de v13 a v18 usando migration.tracking.
        Agrega logging detallado para diagnosticar problemas de mapeo.
        """
        """
        Mapea IDs de v13 a v18 en campos many2one (excepto parent_id que se maneja por separado).
        
        Args:
            records: Lista de registros a mapear
            model: Nombre del modelo en v18
            models_list: Lista de modelos a migrar
        
        Returns:
            Lista de registros con IDs mapeados
        """
        # IMPORTANTE: Obtener el nombre del modelo en v13 (puede ser diferente)
        v13_model = self.get_v13_model_name(model)
        
        # Obtener campos many2one y sus relaciones (excluyendo parent_id)
        # Usar v13_model para obtener los campos desde v13 (donde están los registros originales)
        try:
            many2one_fields = self.get_many2one_fields_info(v13_model, self.v13_conn)
            logger.debug(f"[MAPEO M2O] Campos many2one obtenidos desde v13 para {v13_model} (v13) -> {model} (v18)")
        except Exception as e:
            error_msg = str(e)
            # Si el error es porque el modelo no existe, informar correctamente
            if "doesn't exist" in error_msg.lower() or "object" in error_msg.lower() and "exist" in error_msg.lower():
                logger.warning(f"[MAPEO M2O] El modelo {v13_model} (v13) no existe en v13. Esto puede ser normal si es un modelo nuevo en v18.")
            else:
                logger.warning(f"[MAPEO M2O] Error obteniendo campos many2one para {v13_model} (v13): {e}")
            # NO intentar obtener desde v18 porque los registros vienen de v13
            # Si el modelo no existe en v13, no hay campos many2one que mapear
            many2one_fields = {}
            logger.debug(f"[MAPEO M2O] Usando campos many2one vacíos para {model}")
        
        # Excluir parent_id (se maneja por separado)
        if 'parent_id' in many2one_fields:
            del many2one_fields['parent_id']
        
        # Excluir category_id para uom.uom (se maneja por separado con mapeo especial)
        if model == 'uom.uom' and 'category_id' in many2one_fields:
            del many2one_fields['category_id']
            logger.debug(f"[MAPEO M2O] Excluyendo category_id de uom.uom (se procesa con mapeo especial de categorías UoM)")
        
        # Caso especial: contract_id en sale.subscription.line debe mapearse a sale_subscription_id
        # usando el mapeo de sale.subscription (contract.contract -> sale.subscription)
        # IMPORTANTE: Verificar si hay contract_id en los registros, no solo en many2one_fields
        if model == 'sale.subscription.line':
            # Verificar si algún registro tiene contract_id
            has_contract_id = any('contract_id' in record for record in records)
            if has_contract_id:
                # Mapear contract_id a sale_subscription_id usando mapeo de sale.subscription
                subscription_mapping = self.v18_conn.get_migration_mapping('sale.subscription')
                if subscription_mapping:
                    logger.info(f"[MAPEO M2O] Mapeando contract_id -> sale_subscription_id para {model} usando mapeo de sale.subscription ({len(subscription_mapping)} registros)")
                    mapped_count = 0
                    not_mapped_count = 0
                    for record in records:
                        contract_id = record.get('contract_id', False)
                        if contract_id:
                            # Extraer el ID si viene como tupla [id, name]
                            if isinstance(contract_id, list) and len(contract_id) >= 1:
                                contract_id = contract_id[0]
                            if contract_id:
                                v13_id_str = str(contract_id)
                                if v13_id_str in subscription_mapping:
                                    record['sale_subscription_id'] = subscription_mapping[v13_id_str]
                                    mapped_count += 1
                                    logger.debug(f"  [MAPEO M2O] contract_id v13[{v13_id_str}] -> sale_subscription_id v18[{record['sale_subscription_id']}]")
                                else:
                                    logger.warning(f"  ⚠ [MAPEO M2O] contract_id v13[{v13_id_str}] no encontrado en mapeo de sale.subscription")
                                    not_mapped_count += 1
                                    # Si no hay mapeo, establecer False para evitar errores
                                    record['sale_subscription_id'] = False
                    logger.info(f"[MAPEO M2O] ✓ Mapeados {mapped_count} campos contract_id -> sale_subscription_id, {not_mapped_count} sin mapeo")
                else:
                    logger.warning(f"[MAPEO M2O] ⚠ No se encontró mapeo de sale.subscription para mapear contract_id")
                    # Establecer sale_subscription_id como False para todos los registros
                    for record in records:
                        if 'contract_id' in record:
                            record['sale_subscription_id'] = False
                
                # Eliminar contract_id ya que no existe en v18
                for record in records:
                    if 'contract_id' in record:
                        del record['contract_id']
                
                # Eliminar contract_id de many2one_fields para que no se procese como campo normal
                if 'contract_id' in many2one_fields:
                    del many2one_fields['contract_id']
                    logger.debug(f"[MAPEO M2O] Excluyendo contract_id de sale.subscription.line (ya mapeado a sale_subscription_id)")
        
        if not many2one_fields:
            return records
        
        # Obtener mapeos para cada modelo relacionado
        mappings = {}
        mapping_stats = {}  # Para diagnóstico
        
        logger.info(f"[MAPEO M2O] Modelo: {model}, Campos many2one encontrados: {list(many2one_fields.keys())}")
        
        # Campos especiales que deben mapearse aunque el modelo relacionado no esté en models_list
        # Estos son campos requeridos en v18 que deben mapearse desde v13
        special_fields = {
            'sale.subscription': ['partner_id', 'company_id', 'pricelist_id'],
        }
        
        special_models = {
            'partner_id': 'res.partner',
            'company_id': 'res.company',
            'pricelist_id': 'product.pricelist',
        }
        
        for field_name, relation_model in many2one_fields.items():
            # Verificar si es un campo especial que debe mapearse aunque no esté en models_list
            is_special_field = False
            if model in special_fields and field_name in special_fields[model]:
                is_special_field = True
                # Obtener el modelo relacionado correcto
                if field_name in special_models:
                    relation_model = special_models[field_name]
            
            # EXCEPCIÓN: user_id en res.partner NO debe requerir mapeo de res.users
            # Si res.users no está en models_list, establecer user_id=False directamente sin intentar mapear
            if field_name == 'user_id' and model == 'res.partner' and relation_model == 'res.users':
                if relation_model not in models_list:
                    logger.info(f"[MAPEO M2O] Campo user_id en res.partner -> res.users no está en models_list, se establecerá a False si no tiene mapeo")
                    # Intentar obtener mapeo, pero si no existe, se establecerá a False más adelante
                    mapping = self.v18_conn.get_migration_mapping(relation_model)
                    if mapping:
                        mappings[field_name] = {
                            'model': relation_model,
                            'mapping': mapping
                        }
                        logger.info(f"[MAPEO M2O] ✓ Mapeo cargado para {field_name} -> {relation_model}: {len(mapping)} registros")
                    else:
                        logger.info(f"[MAPEO M2O] No hay mapeo para {field_name} -> {relation_model}, se establecerá a False en res.partner")
                        # No agregar a mappings, se establecerá a False más adelante
                elif relation_model in models_list:
                    # res.users está en models_list, mapear normalmente
                    logger.info(f"[MAPEO M2O] Obteniendo mapeo para {field_name} -> {relation_model}...")
                    mapping = self.v18_conn.get_migration_mapping(relation_model)
                    if mapping:
                        mappings[field_name] = {
                            'model': relation_model,
                            'mapping': mapping
                        }
                        logger.info(f"[MAPEO M2O] ✓ Mapeo cargado para {field_name} -> {relation_model}: {len(mapping)} registros")
                    else:
                        logger.warning(f"[MAPEO M2O] ⚠ No se encontró mapeo para {field_name} -> {relation_model} en migration.tracking")
            elif relation_model in models_list or is_special_field:
                if is_special_field:
                    logger.info(f"[MAPEO M2O] Campo especial {field_name} -> {relation_model} (requerido en {model}, mapeando aunque no esté en models_list)...")
                else:
                    logger.info(f"[MAPEO M2O] Obteniendo mapeo para {field_name} -> {relation_model}...")
                
                mapping = self.v18_conn.get_migration_mapping(relation_model)
                if mapping:
                    mappings[field_name] = {
                        'model': relation_model,
                        'mapping': mapping
                    }
                    # Guardar estadísticas para diagnóstico
                    mapping_stats[field_name] = {
                        'relation_model': relation_model,
                        'total_mapped': len(mapping),
                        'sample_mappings': dict(list(mapping.items())[:5])  # Primeros 5 para diagnóstico
                    }
                    logger.info(f"[MAPEO M2O] ✓ Mapeo cargado para {field_name} -> {relation_model}: {len(mapping)} registros")
                else:
                    logger.warning(f"[MAPEO M2O] ⚠ No se encontró mapeo para {field_name} -> {relation_model} en migration.tracking")
                    mapping_stats[field_name] = {
                        'relation_model': relation_model,
                        'total_mapped': 0,
                        'error': 'No se encontró mapeo en migration.tracking'
                    }
            else:
                logger.debug(f"[MAPEO M2O] Campo {field_name} -> {relation_model} no está en models_list, omitiendo")
        
        # Guardar estadísticas de mapeo en archivo de diagnóstico
        if mapping_stats:
            self._save_mapping_diagnostics(model, mapping_stats)
        
        if not mappings:
            logger.warning(f"[MAPEO M2O] ⚠ No hay mapeos disponibles para {model}, los campos many2one no se mapearán")
            return records
        
        # Mapear IDs en los registros
        # Primero, identificar partners no mapeados para res.users y crearlos en batch
        partners_to_create = {}  # {v13_partner_id: login} para evitar duplicados
        
        if model == 'res.users' and 'partner_id' in mappings:
            # Recopilar todos los partner_ids no mapeados y sus logins correspondientes
            for idx, record in enumerate(records):
                partner_id = record.get('partner_id')
                if partner_id:
                    # Extraer el ID del partner
                    if isinstance(partner_id, (list, tuple)) and len(partner_id) > 0:
                        v13_partner_id = partner_id[0]
                    elif isinstance(partner_id, (int, str)):
                        v13_partner_id = int(partner_id) if isinstance(partner_id, str) else partner_id
                    else:
                        continue
                    
                    # Verificar si está mapeado
                    v13_partner_id_str = str(v13_partner_id)
                    if v13_partner_id_str not in mappings['partner_id']['mapping']:
                        # No está mapeado, agregar a la lista para crear
                        # Usar login si existe, sino usar name, sino usar un nombre genérico
                        login = record.get('login', '')
                        name = record.get('name', '')
                        if login and isinstance(login, str) and login.strip():
                            partner_name = login.strip()
                        elif name and isinstance(name, str) and name.strip():
                            partner_name = name.strip()
                        else:
                            partner_name = f"Partner {v13_partner_id}"
                        
                        if v13_partner_id not in partners_to_create:
                            partners_to_create[v13_partner_id] = partner_name
                            logger.debug(f"[MAPEO M2O] Partner {v13_partner_id} será creado con nombre: {partner_name}")
        
        # Crear partners no mapeados en batch
        created_partners = {}  # {v13_partner_id: v18_partner_id}
        if partners_to_create:
            logger.info(f"[MAPEO M2O] Creando {len(partners_to_create)} res.partner no mapeados para res.users...")
            partner_records = []
            partner_v13_ids = []
            
            for v13_partner_id, partner_name in partners_to_create.items():
                partner_records.append({
                    'name': partner_name,
                    'is_company': False,
                    'customer_rank': 0,
                    'supplier_rank': 0,
                })
                partner_v13_ids.append(v13_partner_id)
                logger.debug(f"[MAPEO M2O] Preparando partner: v13_id={v13_partner_id}, name={partner_name}")
            
            try:
                # Crear partners en batch
                logger.info(f"[MAPEO M2O] Creando {len(partner_records)} partners en batch...")
                created_partner_ids = self.v18_conn.create('res.partner', partner_records)
                logger.info(f"[MAPEO M2O] ✓ Partners creados: {len(created_partner_ids)} IDs recibidos")
                
                # Registrar en migration.tracking
                tracking_data = []
                for v13_partner_id, v18_partner_id in zip(partner_v13_ids, created_partner_ids):
                    created_partners[v13_partner_id] = v18_partner_id
                    logger.info(f"[MAPEO M2O] ✓ Partner mapeado: v13_id={v13_partner_id} -> v18_id={v18_partner_id}")
                    tracking_data.append({
                        'name': f"res.partner - V13:{v13_partner_id} -> V18:{v18_partner_id} (creado automáticamente para res.users)",
                        'model_name': 'res.partner',
                        'v13_id': v13_partner_id,
                        'v18_id': v18_partner_id,
                        'status': 'created',
                    })
                
                if tracking_data:
                    try:
                        self.v18_conn.models.execute_kw(
                            self.v18_conn.db, self.v18_conn.uid, self.v18_conn.password,
                            'migration.tracking', 'create',
                            [tracking_data]
                        )
                        logger.info(f"[MAPEO M2O] ✓ Creados {len(created_partners)} res.partner y registrados en migration.tracking")
                    except Exception as tracking_error:
                        logger.warning(f"[MAPEO M2O] ⚠ No se pudieron registrar algunos partners en migration.tracking: {tracking_error}")
            except Exception as partner_error:
                logger.error(f"[MAPEO M2O] ✗ Error creando res.partner en batch: {partner_error}")
        
        # Mapear IDs en los registros
        mapped_records = []
        mapped_count = 0
        not_mapped_count = 0
        not_mapped_details = []  # Para diagnóstico
        
        for idx, record in enumerate(records):
            mapped_record = record.copy()
            
            for field_name, mapping_info in mappings.items():
                if field_name in mapped_record:
                    v13_id = mapped_record[field_name]
                    
                    # many2one viene como [id, name] en search_read de Odoo
                    if v13_id and isinstance(v13_id, (list, tuple)) and len(v13_id) > 0:
                        v13_id_value = v13_id[0]
                    elif v13_id and isinstance(v13_id, (int, str)):
                        v13_id_value = int(v13_id) if isinstance(v13_id, str) else v13_id
                    elif v13_id is False or v13_id is None:
                        # Campo vacío, mantener False
                        continue
                    else:
                        logger.warning(f"[MAPEO M2O] Formato desconocido para {field_name} en registro {idx}: {type(v13_id)} = {v13_id}")
                        continue
                    
                    v13_id_str = str(v13_id_value)
                    if v13_id_str in mapping_info['mapping']:
                        v18_id = mapping_info['mapping'][v13_id_str]
                        mapped_record[field_name] = v18_id
                        mapped_count += 1
                        # Log detallado para los primeros registros y campos críticos
                        if idx < 3 or field_name in ['user_id', 'partner_id', 'team_id']:
                            logger.info(f"[MAPEO M2O] Registro {idx}: {field_name} v13_id={v13_id_value} -> v18_id={v18_id}")
                    else:
                        # IMPORTANTE: user_id en res.partner debe establecerse a False inmediatamente si no hay mapeo
                        # NO debe requerir que res.users esté mapeado
                        if field_name == 'user_id' and model == 'res.partner':
                            logger.info(f"[MAPEO M2O] user_id={v13_id_value} no tiene mapeo en res.users para res.partner, estableciendo False (no requiere res.users mapeado)")
                            mapped_record[field_name] = False
                            continue
                        
                        # Si no hay mapeo, verificar si se creó un partner para este caso
                        not_mapped_count += 1
                        not_mapped_details.append({
                            'record_idx': idx,
                            'field_name': field_name,
                            'v13_id': v13_id_value,
                            'relation_model': mapping_info['model']
                        })
                        
                        # Caso especial: partner_id en res.users
                        # Si el partner_id no está mapeado pero se creó un partner, usarlo
                        if field_name == 'partner_id' and model == 'res.users':
                            if v13_id_value in created_partners:
                                new_partner_id = created_partners[v13_id_value]
                                mapped_record[field_name] = new_partner_id
                                mapped_count += 1
                                logger.info(f"[MAPEO M2O] ✓ Usando res.partner creado (ID: {new_partner_id}) para res.users (partner_id v13={v13_id_value})")
                            else:
                                # El partner no se pudo crear, establecer False para evitar error
                                logger.error(f"[MAPEO M2O] ✗ CRÍTICO: partner_id={v13_id_value} no está mapeado y no se creó automáticamente para res.users, estableciendo False")
                                mapped_record[field_name] = False
                        # Para campos críticos (partner_id, company_id) en sale.subscription, no establecer False
                        # porque son requeridos. El error se detectará en prepare_records_for_creation
                        elif model == 'sale.subscription' and field_name in ['partner_id', 'company_id']:
                            logger.error(f"[MAPEO M2O] ✗ ERROR CRÍTICO: No se encontró mapeo para {field_name}={v13_id_value} (v13) en {mapping_info['model']}. Este campo es requerido en sale.subscription.")
                            # Dejar el campo con el valor original [id, name] para que prepare_records_for_creation lo maneje
                            # No establecer False porque es requerido
                        # IMPORTANTE: user_id en res.partner debe ser False si no hay mapeo para evitar errores de foreign key
                        elif field_name == 'user_id' and model == 'res.partner':
                            logger.warning(f"[MAPEO M2O] ⚠ CRÍTICO: No se encontró mapeo para user_id={v13_id_value} (v13) en res.users para res.partner, estableciendo False para evitar error de foreign key")
                            mapped_record[field_name] = False
                        else:
                            # Para otros casos, poner False (sin relación)
                            logger.warning(f"[MAPEO M2O] ⚠ No se encontró mapeo para {field_name}={v13_id_value} (v13) en {mapping_info['model']}, estableciendo False")
                            mapped_record[field_name] = False
            
            mapped_records.append(mapped_record)
        
        if mapped_count > 0:
            logger.info(f"[MAPEO M2O] ✓ Mapeados {mapped_count} campos many2one")
        
        if not_mapped_count > 0:
            logger.warning(f"[MAPEO M2O] ⚠ {not_mapped_count} campos many2one no pudieron ser mapeados (establecidos a False)")
            # Guardar detalles de no mapeados en archivo de diagnóstico
            self._save_unmapped_details(model, not_mapped_details)
        
        return mapped_records
    
    def _save_mapping_diagnostics(self, model: str, mapping_stats: Dict):
        """
        Guarda estadísticas de mapeo en un archivo JSON para diagnóstico.
        
        Args:
            model: Nombre del modelo
            mapping_stats: Diccionario con estadísticas de mapeo
        """
        try:
            diagnostics_dir = os.path.join(self.errors_dir, 'mapping_diagnostics')
            os.makedirs(diagnostics_dir, exist_ok=True)
            
            diagnostics_file = os.path.join(diagnostics_dir, f"mapping_{model.replace('.', '_')}.json")
            
            diagnostics_data = {
                'model': model,
                'timestamp': datetime.now().isoformat(),
                'mapping_stats': mapping_stats
            }
            
            with open(diagnostics_file, 'w', encoding='utf-8') as f:
                json.dump(diagnostics_data, f, indent=2, ensure_ascii=False, default=str)
            
            logger.debug(f"[DIAGNÓSTICO] Estadísticas de mapeo guardadas en {diagnostics_file}")
        except Exception as e:
            logger.warning(f"[DIAGNÓSTICO] No se pudo guardar estadísticas de mapeo: {e}")
    
    def _save_unmapped_details(self, model: str, not_mapped_details: List[Dict]):
        """
        Guarda detalles de campos many2one que no pudieron ser mapeados.
        
        Args:
            model: Nombre del modelo
            not_mapped_details: Lista de detalles de campos no mapeados
        """
        try:
            diagnostics_dir = os.path.join(self.errors_dir, 'mapping_diagnostics')
            os.makedirs(diagnostics_dir, exist_ok=True)
            
            unmapped_file = os.path.join(diagnostics_dir, f"unmapped_{model.replace('.', '_')}.json")
            
            # Cargar datos existentes o crear nuevo
            if os.path.exists(unmapped_file):
                with open(unmapped_file, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
            else:
                existing_data = {
                    'model': model,
                    'unmapped_details': []
                }
            
            # Agregar nuevos detalles
            existing_data['unmapped_details'].extend(not_mapped_details)
            existing_data['last_updated'] = datetime.now().isoformat()
            existing_data['total_unmapped'] = len(existing_data['unmapped_details'])
            
            with open(unmapped_file, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, indent=2, ensure_ascii=False, default=str)
            
            logger.debug(f"[DIAGNÓSTICO] Detalles de no mapeados guardados en {unmapped_file}")
        except Exception as e:
            logger.warning(f"[DIAGNÓSTICO] No se pudo guardar detalles de no mapeados: {e}")
    
    def get_import_filepath(self, model: str) -> str:
        """
        Obtiene la ruta del archivo de importación para un modelo.
        
        Args:
            model: Nombre del modelo
        
        Returns:
            Ruta del archivo de importación
        """
        filename = f"import_{model.replace('.', '_')}.json"
        return os.path.join(self.output_dir, filename)
    
    def get_import_filepath_m2m(self, model1: str, model2: str) -> str:
        """
        Obtiene la ruta del archivo de importación para una tabla intermedia many2many.
        
        Args:
            model1: Nombre del primer modelo
            model2: Nombre del segundo modelo
        
        Returns:
            Ruta del archivo de importación
        """
        # Ordenar los nombres para consistencia
        models = sorted([model1.replace('.', '_'), model2.replace('.', '_')])
        filename = f"import_{models[0]}_{models[1]}.json"
        return os.path.join(self.output_dir, filename)
    
    def get_many2many_tables(self, model: str, conn: OdooConnection, 
                            models_list: List[str] = None) -> List[Dict[str, str]]:
        """
        Obtiene las tablas intermedias many2many de un modelo.
        Solo incluye relaciones donde el modelo relacionado esté en models_list.
        
        Args:
            model: Nombre del modelo
            conn: Conexión Odoo
            models_list: Lista de modelos a migrar (para filtrar relaciones)
        
        Returns:
            Lista de diccionarios con información de tablas intermedias:
            [{'field_name': 'campo', 'relation_table': 'tabla_intermedia', 'relation': 'modelo_relacionado'}]
        """
        many2many_tables = []
        try:
            fields_info = conn.get_fields(model)
            
            logger.debug(f"[M2M] Analizando campos de {model} para detectar many2many...")
            
            for field_name, field_info in fields_info.items():
                field_type = field_info.get('type', '')
                if field_type == 'many2many':
                    relation = field_info.get('relation', '')
                    relation_table = field_info.get('relation_table', '')
                    
                    logger.debug(f"[M2M] Campo many2many encontrado: {field_name} -> {relation} (tabla: {relation_table})")
                    
                    # Filtrar: solo incluir si el modelo relacionado está en models_list
                    if models_list and relation not in models_list:
                        logger.debug(f"[M2M] Excluyendo relación {field_name} -> {relation} (no está en models_to_migrate.txt)")
                        continue
                    
                    # Si no hay relation_table en el campo, intentar construirla
                    if not relation_table and relation:
                        # En Odoo, las tablas intermedias many2many siguen el patrón:
                        # modelo1_modelo2_rel o modelo1_modelo2_rel_xxx
                        # Ordenar los nombres de modelos para consistencia
                        model_parts = sorted([model.replace('.', '_'), relation.replace('.', '_')])
                        relation_table = f"{model_parts[0]}_{model_parts[1]}_rel"
                        logger.debug(f"[M2M] Tabla intermedia construida: {relation_table}")
                    
                    if relation and relation_table:
                        many2many_tables.append({
                            'field_name': field_name,
                            'relation_table': relation_table,
                            'relation': relation
                        })
                        logger.info(f"[M2M] ✓ Relación many2many detectada: {field_name} -> {relation} (tabla: {relation_table})")
                    else:
                        logger.warning(f"[M2M] ⚠ Campo many2many {field_name} sin relation o relation_table, omitiendo")
            
            if not many2many_tables:
                logger.debug(f"[M2M] No se encontraron relaciones many2many en {model}")
            
            return many2many_tables
        except Exception as e:
            logger.warning(f"⚠ No se pudieron obtener tablas many2many de {model}: {e}")
            import traceback
            logger.debug(f"[M2M] Error detallado: {traceback.format_exc()}")
            return []
    
    def _detect_m2m_from_fields(self, model: str, models_list: List[str] = None) -> List[Dict[str, str]]:
        """
        Detecta relaciones many2many automáticamente desde los campos del modelo.
        Este método es genérico y funciona para cualquier modelo sin necesidad de hardcodear relaciones.
        
        Args:
            model: Nombre del modelo
            models_list: Lista de modelos a migrar
        
        Returns:
            Lista de relaciones many2many detectadas
        """
        detected_relations = []
        
        if not models_list:
            return detected_relations
        
        try:
            # IMPORTANTE: model es el nombre en v18, pero necesitamos verificar que exista
            # Si no existe, intentar obtener el nombre en v13 para logging
            try:
                # Obtener campos del modelo desde v18
                fields_info = self.v18_conn.get_fields(model)
            except Exception as get_fields_error:
                # Si falla, obtener el nombre del modelo en v13 para mejor mensaje de error
                v13_model = self.get_v13_model_name(model)
                if v13_model != model:
                    logger.warning(f"[M2M AUTO] No se pudieron obtener campos de {model} (v18), pero el modelo existe en v13 como {v13_model}")
                else:
                    logger.warning(f"[M2M AUTO] No se pudieron obtener campos de {model}: {get_fields_error}")
                return detected_relations
            
            if not fields_info:
                logger.debug(f"[M2M AUTO] No se pudieron obtener campos para {model}")
                return detected_relations
            
            # Buscar campos many2many
            for field_name, field_info in fields_info.items():
                field_type = field_info.get('type', '')
                
                if field_type == 'many2many':
                    relation_model = field_info.get('relation', '')
                    relation_table = field_info.get('relation_table', '')
                    
                    # Solo incluir si el modelo relacionado está en models_list
                    if relation_model and relation_model in models_list:
                        # Si no hay relation_table, intentar construirla
                        if not relation_table:
                            # Construir nombre de tabla usando convención de Odoo
                            model1_name = model.replace('.', '_')
                            model2_name = relation_model.replace('.', '_')
                            # Ordenar para consistencia
                            models_sorted = sorted([model1_name, model2_name])
                            relation_table = f"{models_sorted[0]}_{models_sorted[1]}_rel"
                            logger.debug(f"[M2M AUTO] Construida tabla intermedia: {relation_table}")
                        
                        detected_relations.append({
                            'field_name': field_name,
                            'relation_table': relation_table,
                            'relation': relation_model
                        })
                        logger.info(f"[M2M AUTO] Relación detectada automáticamente: {model}.{field_name} -> {relation_model} (tabla: {relation_table})")
            
            return detected_relations
            
        except Exception as e:
            logger.warning(f"[M2M AUTO] Error detectando relaciones many2many para {model}: {e}")
            return detected_relations
    
    def _check_known_many2many(self, model: str, models_list: List[str] = None) -> List[Dict[str, str]]:
        """
        DEPRECATED: Usar _detect_m2m_from_fields en su lugar.
        Este método se mantiene por compatibilidad pero ahora delega a la detección automática.
        
        Args:
            model: Nombre del modelo
            models_list: Lista de modelos a migrar
        
        Returns:
            Lista de relaciones many2many detectadas
        """
        # Usar detección automática en lugar de relaciones hardcodeadas
        return self._detect_m2m_from_fields(model, models_list)
    
    def export_m2m_table(self, relation_table: str, model1: str, model2: str, 
                         source_model: str = None, field_name: str = None) -> str:
        """
        Exporta datos de una tabla intermedia many2many.
        
        Args:
            relation_table: Nombre de la tabla intermedia
            model1: Nombre del primer modelo
            model2: Nombre del segundo modelo
            source_model: Modelo desde el cual se detectó la relación (opcional, para optimizar búsqueda)
            field_name: Nombre del campo many2many que detectó la relación (opcional, para optimizar búsqueda)
        
        Returns:
            Ruta del archivo JSON creado
        """
        filepath = self.get_import_filepath_m2m(model1, model2)
        
        # Verificar si el archivo ya existe
        if os.path.exists(filepath):
            logger.info(f"[M2M] Archivo de importación existente: {filepath}")
            logger.info("[M2M] No se exportará nuevamente")
            return filepath
        
        logger.info(f"[M2M] Exportando tabla intermedia: {relation_table}")
        logger.info(f"[M2M] Relación entre: {model1} <-> {model2}")
        
        # Intentar obtener información completa de la tabla intermedia
        table_info = self.v13_conn.get_table_info(relation_table)
        
        if table_info['accessible']:
            logger.info("[M2M] ✓ Tabla intermedia accesible como modelo")
            logger.info(f"[M2M] Campos disponibles: {len(table_info['fields'])} campos")
            if table_info['sample']:
                logger.debug(f"[M2M] Muestra de campos: {list(table_info['sample'].keys())}")
            fields = table_info['fields']
        else:
            logger.warning("[M2M] ⚠ Tabla intermedia NO accesible directamente como modelo")
            if table_info['error']:
                logger.debug(f"[M2M] Error: {table_info['error']}")
            # Construir campos esperados como fallback
            fields = None
        
        # Si no se obtuvieron campos desde get_table_info, intentar métodos alternativos
        if not fields:
            try:
                # Intentar obtener campos usando fields_get (si es un modelo)
                try:
                    fields_info = self.v13_conn.get_fields(relation_table)
                    if fields_info:
                        # Obtener TODOS los campos, incluyendo los de relación
                        fields = [f for f in fields_info.keys() if f not in ['create_uid', 'write_uid', 'create_date', 'write_date']]
                        logger.info(f"[M2M] Campos obtenidos desde fields_get: {len(fields)} campos")
                        logger.debug(f"[M2M] Campos: {fields}")
                except Exception:
                    # Si fields_get falla, intentar leer un registro de muestra SIN especificar campos
                    # Esto devolverá todos los campos disponibles
                    try:
                        logger.info("[M2M] Intentando leer muestra sin especificar campos para obtener todos...")
                        sample = self.v13_conn.search_read(
                            relation_table,
                            [],
                            [],  # Lista vacía = todos los campos
                            limit=1
                        )
                        if sample and len(sample) > 0:
                            # Obtener TODOS los campos del primer registro
                            fields = list(sample[0].keys())
                            # Solo excluir campos de auditoría, pero mantener todos los demás
                            fields = [f for f in fields if f not in ['create_uid', 'write_uid', 'create_date', 'write_date']]
                            logger.info(f"[M2M] Campos obtenidos desde muestra: {len(fields)} campos")
                            logger.debug(f"[M2M] Campos encontrados: {fields}")
                        else:
                            logger.warning(f"[M2M] No se encontraron registros de muestra en {relation_table}")
                            # Si no hay registros, intentar construir campos esperados
                            logger.info("[M2M] Construyendo campos esperados para tabla intermedia...")
                            # En tablas many2many típicamente hay: id, y campos con nombres de los modelos
                            model1_field = model1.replace('.', '_') + '_id'
                            model2_field = model2.replace('.', '_') + '_id'
                            fields = ['id', model1_field, model2_field]
                            logger.info(f"[M2M] Campos construidos: {fields}")
                    except Exception as e2:
                        logger.warning(f"[M2M] No se pudo acceder a {relation_table} como modelo: {e2}")
                        # Intentar construir campos esperados como último recurso
                        logger.info("[M2M] Construyendo campos esperados como último recurso...")
                        model1_field = model1.replace('.', '_') + '_id'
                        model2_field = model2.replace('.', '_') + '_id'
                        fields = ['id', model1_field, model2_field]
                        logger.info(f"[M2M] Campos construidos: {fields}")
            except Exception as e:
                logger.error(f"[M2M] Error obteniendo campos de {relation_table}: {e}")
                # Como último recurso, construir campos esperados
                logger.info("[M2M] Construyendo campos esperados como último recurso...")
                model1_field = model1.replace('.', '_') + '_id'
                model2_field = model2.replace('.', '_') + '_id'
                fields = ['id', model1_field, model2_field]
                logger.info(f"[M2M] Campos construidos: {fields}")
        
        # Asegurar que fields no sea None o vacío
        if not fields:
            logger.warning("[M2M] No se pudieron obtener campos, usando campos básicos")
            model1_field = model1.replace('.', '_') + '_id'
            model2_field = model2.replace('.', '_') + '_id'
            fields = ['id', model1_field, model2_field]
        
        # Leer todos los registros
        # Las tablas intermedias many2many pueden no ser modelos accesibles directamente
        # Intentamos diferentes métodos
        all_records = []
        
        # Método 1: Intentar leer como modelo directamente
        logger.info(f"[M2M] Intentando leer {relation_table} como modelo...")
        try:
            offset = 0
            batch_count = 0
            
            while True:
                batch_count += 1
                read_fields = fields if fields else []
                batch = self.v13_conn.search_read(
                    relation_table,
                    [],
                    read_fields,
                    limit=self.batch_size,
                    offset=offset
                )
                
                if not batch:
                    break
                
                all_records.extend(batch)
                offset += len(batch)
                logger.info(f"[M2M] Batch {batch_count}: Leídos {len(all_records)} registros de {relation_table}...")
            
            if all_records:
                logger.info(f"[M2M] ✓ Método 1 exitoso: {len(all_records)} registros leídos")
        except Exception as e:
            logger.warning(f"[M2M] Método 1 falló: {e}")
            logger.info("[M2M] Intentando método alternativo: leer desde campos many2many...")
            
            # Método 2: Leer desde los modelos relacionados y reconstruir la tabla
            try:
                # Si tenemos source_model y field_name, usarlos directamente
                # Si no, buscar en ambos modelos
                models_to_check = []
                if source_model and field_name:
                    models_to_check = [(source_model, field_name)]
                else:
                    models_to_check = [(model1, None), (model2, None)]
                
                for check_model, check_field in models_to_check:
                    try:
                        target_model = model2 if check_model == model1 else model1
                        fields_info = self.v13_conn.get_fields(check_model)
                        
                        # Si tenemos un campo específico, usarlo directamente
                        if check_field:
                            field_info = fields_info.get(check_field)
                            if field_info and field_info.get('type') == 'many2many':
                                relation = field_info.get('relation', '')
                                if relation == target_model:
                                    logger.info(f"[M2M] Usando campo especificado: {check_model}.{check_field} -> {target_model}")
                                    fields_to_check = [(check_field, field_info)]
                                else:
                                    logger.debug(f"[M2M] Campo {check_field} no apunta a {target_model}, buscando otros...")
                                    fields_to_check = []
                                    for fn, fi in fields_info.items():
                                        if fi.get('type') == 'many2many' and fi.get('relation') == target_model:
                                            fields_to_check.append((fn, fi))
                            else:
                                fields_to_check = []
                                for fn, fi in fields_info.items():
                                    if fi.get('type') == 'many2many' and fi.get('relation') == target_model:
                                        fields_to_check.append((fn, fi))
                        else:
                            # Buscar todos los campos many2many que apunten al modelo objetivo
                            fields_to_check = []
                            for fn, fi in fields_info.items():
                                if fi.get('type') == 'many2many' and fi.get('relation') == target_model:
                                    fields_to_check.append((fn, fi))
                        
                        for field_name, field_info in fields_to_check:
                            relation = field_info.get('relation', '')
                            field_relation_table = field_info.get('relation_table', '')
                            
                            # Construir posibles nombres de tabla intermedia
                            model_parts = sorted([model1.replace('.', '_'), model2.replace('.', '_')])
                            expected_table = f"{model_parts[0]}_{model_parts[1]}_rel"
                            
                            # Verificar que la tabla intermedia coincida
                            if field_relation_table == relation_table or field_relation_table == expected_table:
                                logger.info(f"[M2M] Campo many2many encontrado: {check_model}.{field_name} -> {target_model}")
                                
                                # Leer todos los registros del modelo fuente con el campo many2many
                                logger.info(f"[M2M] Leyendo registros de {check_model} con campo {field_name}...")
                                source_records = []
                                offset = 0
                                
                                while True:
                                    batch = self.v13_conn.search_read(
                                        check_model,
                                        [],
                                        ['id', field_name],
                                        limit=self.batch_size,
                                        offset=offset
                                    )
                                    
                                    if not batch:
                                        break
                                    
                                    source_records.extend(batch)
                                    offset += len(batch)
                                    
                                    if offset % 1000 == 0:
                                        logger.info(f"[M2M] Leídos {offset} registros de {check_model}...")
                                
                                logger.info(f"[M2M] Leídos {len(source_records)} registros de {check_model}")
                                
                                # Reconstruir la tabla intermedia desde los datos many2many
                                model1_field = model1.replace('.', '_') + '_id'
                                model2_field = model2.replace('.', '_') + '_id'
                                
                                for record in source_records:
                                    source_id = record.get('id')
                                    m2m_field_value = record.get(field_name, [])
                                    
                                    # m2m_field_value viene como lista de tuplas [(id, name), ...]
                                    if isinstance(m2m_field_value, list):
                                        for related_item in m2m_field_value:
                                            if isinstance(related_item, (list, tuple)) and len(related_item) > 0:
                                                related_id = related_item[0]
                                                
                                                # Determinar qué campo corresponde a cada modelo
                                                if check_model == model1:
                                                    m2m_record = {
                                                        'id': len(all_records) + 1,  # ID temporal
                                                        model1_field: source_id,
                                                        model2_field: related_id
                                                    }
                                                else:
                                                    m2m_record = {
                                                        'id': len(all_records) + 1,  # ID temporal
                                                        model1_field: related_id,
                                                        model2_field: source_id
                                                    }
                                                
                                                all_records.append(m2m_record)
                                
                                if all_records:
                                    logger.info(f"[M2M] ✓ Método 2 exitoso: {len(all_records)} relaciones reconstruidas")
                                    break
                    except Exception as e2:
                        logger.debug(f"[M2M] Error procesando {check_model}: {e2}")
                        continue
                    
                    if all_records:
                        break
                
                if not all_records:
                    logger.warning(f"[M2M] No se pudieron leer registros de {relation_table} con ningún método")
            except Exception as e:
                logger.error(f"[M2M] Error en método alternativo: {e}")
                import traceback
                logger.debug(f"[M2M] Traceback: {traceback.format_exc()}")
        
        # Guardar en JSON
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump({
                'relation_table': relation_table,
                'model1': model1,
                'model2': model2,
                'export_date': timestamp,
                'total_records': len(all_records),
                'fields': fields,
                'records': all_records
            }, f, indent=2, ensure_ascii=False, default=str)
        
        logger.info(f"[M2M] ✓ Exportados {len(all_records)} registros a {filepath}")
        return filepath
    
    def export_model_data(self, model: str, allow_many2one: bool = False, 
                         models_list: List[str] = None) -> str:
        """
        Exporta datos de un modelo desde v13 a JSON.
        Si el archivo ya existe, lo retorna sin exportar nuevamente.
        
        Args:
            model: Nombre del modelo en v18
            allow_many2one: Si True, incluye campos many2one
            models_list: Lista de modelos a migrar (para filtrar many2one)
        
        Returns:
            Ruta del archivo JSON (creado o existente)
        """
        # Obtener el nombre del modelo en v13 (puede ser diferente)
        v13_model = self.get_v13_model_name(model)
        
        filepath = self.get_import_filepath(model)
        
        # Verificar si el archivo ya existe
        if os.path.exists(filepath):
            logger.info("=" * 80)
            logger.info("ARCHIVO DE IMPORTACIÓN EXISTENTE")
            logger.info(f"Modelo: {model}")
            logger.info(f"Archivo: {filepath}")
            logger.info("=" * 80)
            logger.info("[INFO] El archivo de importación ya existe, no se exportará nuevamente")
            logger.info("[INFO] Continuando con la preparación y migración...")
            logger.info("=" * 80)
            return filepath
        
        logger.info("=" * 80)
        logger.info("INICIANDO EXPORTACIÓN DE DATOS")
        logger.info(f"Modelo: {model}")
        logger.info(f"Incluir many2one: {allow_many2one}")
        logger.info("=" * 80)
        
        # Obtener el nombre del modelo en v13 (puede ser diferente)
        v13_model = self.get_v13_model_name(model)
        
        logger.info(f"[PREPARACIÓN] Obteniendo campos almacenados para {model} (v13: {v13_model})...")
        try:
            # Pasar el nombre del modelo en v18 para verificaciones especiales (p.ej., sale.subscription necesita partner_id aunque res.partner no esté en la lista)
            fields = self.get_stored_fields(v13_model, self.v13_conn, allow_many2one, models_list, v18_model_name=model)
        except Exception as e:
            error_str = str(e)
            # Verificar si el modelo no existe en v13
            if "doesn't exist" in error_str.lower() or ("object" in error_str.lower() and "exist" in error_str.lower()):
                logger.error(f"✗ El modelo {v13_model} no existe en v13: {error_str}")
                logger.warning(f"⚠ Omitiendo migración de {model} (v13: {v13_model}) - no disponible en v13")
                # Crear archivo vacío para indicar que se intentó pero no existe
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump({
                        'model': model,
                        'export_date': datetime.now().strftime('%Y%m%d_%H%M%S'),
                        'total_records': 0,
                        'fields': [],
                        'records': [],
                        'error': f"Modelo no existe en v13: {error_str}"
                    }, f, indent=2, ensure_ascii=False, default=str)
                logger.info(f"[GUARDADO] Archivo vacío creado en: {filepath}")
                return None  # Retornar None para indicar que el modelo no existe
            else:
                # Otro tipo de error, re-lanzar
                logger.error(f"✗ Error obteniendo campos de {model}: {e}")
                raise
        
        if not fields:
            logger.warning(f"⚠ No se encontraron campos almacenados para {model}")
            return None
        
        logger.info(f"[PREPARACIÓN] ✓ Campos a exportar: {len(fields)}")
        
        logger.info("[EXPORTACIÓN] Iniciando lectura de registros desde v13...")
        
        # Para res.users, solo importar usuarios internos (share=False), incluyendo archivados
        # Para res.partner, incluir tanto archivados como no archivados
        domain = []
        context = None
        if model == 'res.users':
            domain = [['share', '=', False]]
            # Incluir usuarios archivados usando active_test=False
            context = {'active_test': False}
            logger.info("[EXPORTACIÓN] Filtrando solo usuarios internos (share=False) para res.users, incluyendo archivados")
        elif model == 'res.partner':
            # Incluir partners archivados usando active_test=False
            context = {'active_test': False}
            logger.info("[EXPORTACIÓN] Incluyendo partners archivados y no archivados para res.partner")
        
        all_records = []
        offset = 0
        batch_count = 0
        
        try:
            while True:
                batch_count += 1
                batch = self.v13_conn.search_read(
                    v13_model,  # Usar el nombre del modelo en v13
                    domain,
                    fields,
                    limit=self.batch_size,
                    offset=offset,
                    context=context
                )
                
                if not batch:
                    break
                
                all_records.extend(batch)
                offset += len(batch)
                logger.info(f"[EXPORTACIÓN] Batch {batch_count}: Leídos {len(all_records)} registros en total...")
        except Exception as e:
            error_str = str(e)
            # Verificar si el modelo no existe en v13
            if "doesn't exist" in error_str.lower() or ("object" in error_str.lower() and "exist" in error_str.lower()):
                logger.error(f"✗ El modelo {v13_model} no existe en v13: {error_str}")
                logger.warning(f"⚠ Omitiendo migración de {model} (v13: {v13_model}) - no disponible en v13")
                # Crear archivo vacío para indicar que se intentó pero no existe
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump({
                        'model': model,
                        'v13_model': v13_model,
                        'export_date': datetime.now().strftime('%Y%m%d_%H%M%S'),
                        'total_records': 0,
                        'fields': fields if 'fields' in locals() else [],
                        'records': [],
                        'error': f"Modelo no existe en v13: {error_str}"
                    }, f, indent=2, ensure_ascii=False, default=str)
                logger.info(f"[GUARDADO] Archivo vacío creado en: {filepath}")
                return None  # Retornar None para indicar que el modelo no existe
            else:
                # Otro tipo de error, re-lanzar
                logger.error(f"✗ Error leyendo {model}: {e}")
                raise
        
        logger.info(f"[EXPORTACIÓN] ✓ Total de registros exportados: {len(all_records)}")
        
        logger.info("[GUARDADO] Guardando datos en archivo JSON...")
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump({
                'model': model,
                'export_date': timestamp,
                'total_records': len(all_records),
                'fields': fields,
                'records': all_records
            }, f, indent=2, ensure_ascii=False, default=str)
        
        logger.info(f"[GUARDADO] ✓ Datos guardados en: {filepath}")
        logger.info("=" * 80)
        return filepath
    
    def migrate_model(self, model: str, json_file: str = None, 
                     allow_many2one: bool = False, 
                     models_list: List[str] = None) -> Dict[str, Any]:
        """
        Migra datos de un modelo de v13 a v18.
        
        Args:
            model: Nombre del modelo
            json_file: Ruta del archivo JSON (si None, exporta primero)
            allow_many2one: Si True, incluye campos many2one
            models_list: Lista de modelos a migrar (para mapear dependencias)
        
        Returns:
            Diccionario con estadísticas de migración
        """
        self.current_model = model
        model_num = self.current_model_index + 1
        
        logger.info("")
        logger.info("=" * 80)
        logger.info(f"INICIANDO MIGRACIÓN DE TABLA: {model}")
        logger.info(f"Progreso: {model_num} / {self.total_models}")
        logger.info("=" * 80)
        
        # Verificar y crear plantillas de suscripción antes de migrar sale.subscription
        if model == 'sale.subscription':
            if not self.ensure_subscription_templates():
                logger.error("[ERROR CRÍTICO] ✗ No se pudieron verificar/crear plantillas de suscripción. Abortando migración de sale.subscription.")
                return {
                    'created': 0,
                    'skipped': 0,
                    'errors': 0,
                    'warning': 'No se pudieron verificar/crear plantillas de suscripción'
                }
        
        # Verificar y crear etiqueta "OLDv13" antes de migrar productos
        if model in ['product.template', 'product.product']:
            if self.oldv13_tag_id is None:
                logger.info("[VERIFICACIÓN] Verificando/creando etiqueta 'OLDv13' para productos...")
                self.oldv13_tag_id = self.get_or_create_oldv13_tag()
                if not self.oldv13_tag_id:
                    logger.error("[ERROR CRÍTICO] ✗ No se pudo obtener/crear la etiqueta 'OLDv13'. Los productos se migrarán sin esta etiqueta.")
                else:
                    logger.info(f"[VERIFICACIÓN] ✓ Etiqueta 'OLDv13' lista (ID: {self.oldv13_tag_id})")
        
        # Obtener el nombre del modelo en v13 (puede ser diferente)
        v13_model = self.get_v13_model_name(model)
        
        # Contar registros en v13 (puede fallar si el modelo no existe)
        logger.info(f"[CONTEO] Contando registros en v13 (modelo: {v13_model})...")
        try:
            # Para res.users, incluir usuarios archivados en el conteo y filtrar solo internos
            # Para res.partner, incluir tanto archivados como no archivados en el conteo
            domain = None
            context = None
            if model == 'res.users':
                domain = [['share', '=', False]]
                context = {'active_test': False}
                logger.info("[CONTEO] Filtrando solo usuarios internos (share=False) e incluyendo archivados para res.users")
            elif model == 'res.partner':
                context = {'active_test': False}
                logger.info("[CONTEO] Incluyendo partners archivados y no archivados para res.partner")
            
            v13_count = self.v13_conn.count_records(v13_model, domain=domain, context=context)
            logger.info(f"[CONTEO] ✓ Registros en v13: {v13_count}")
        except Exception as e:
            error_str = str(e)
            if "doesn't exist" in error_str.lower() or ("object" in error_str.lower() and "exist" in error_str.lower()):
                logger.warning(f"⚠ El modelo {v13_model} no existe en v13: {error_str}")
                logger.info(f"⚠ Omitiendo migración de {model} (v13: {v13_model}) y continuando con el siguiente modelo...")
                return {
                    'created': 0,
                    'skipped': 0,
                    'errors': 0,
                    'warning': f'Modelo no existe en v13: {error_str}'
                }
            else:
                logger.warning(f"⚠ Error contando registros en v13: {e}")
                v13_count = 0
        
        # Contar registros en migration.tracking (v18)
        logger.info("[CONTEO] Contando registros en migration.tracking (v18)...")
        v18_count = self.v18_conn.count_migration_tracking(model)
        logger.info(f"[CONTEO] ✓ Registros en migration.tracking (v18): {v18_count}")
        
        # Calcular diferencia
        diferencia = v13_count - v18_count
        if diferencia > 0:
            logger.info(f"[CONTEO] ⚠ Faltan {diferencia} registros por migrar")
        elif diferencia < 0:
            logger.info(f"[CONTEO] ⚠ Hay {abs(diferencia)} registros más en v18 que en v13")
        else:
            logger.info("[CONTEO] ✓ Todos los registros están migrados")
        
        logger.info("=" * 80)
        
        # PASO 1: Importar datos desde v13
        if not json_file:
            logger.info("[PASO 1/4] Importando datos desde v13...")
            json_file = self.export_model_data(model, allow_many2one, models_list)
            if not json_file:
                logger.warning(f"⚠ No se pudo exportar datos de {model} (puede que el modelo no exista en v13)")
                logger.info(f"⚠ Omitiendo migración de {model} y continuando con el siguiente modelo...")
                return {
                    'created': 0,
                    'skipped': 0,
                    'errors': 0,
                    'warning': 'Modelo no existe en v13 o no se pudo exportar datos'
                }
        else:
            logger.info(f"[PASO 1/4] Usando archivo JSON especificado: {json_file}")
        
        # Detectar y importar tablas intermedias many2many
        logger.info("[PASO 1/4] Detectando tablas intermedias many2many...")
        m2m_tables = self.get_many2many_tables(model, self.v13_conn, models_list)
        
        if m2m_tables:
            logger.info(f"[PASO 1/4] Encontradas {len(m2m_tables)} relaciones many2many")
            for m2m_info in m2m_tables:
                field_name = m2m_info['field_name']
                relation_table = m2m_info['relation_table']
                relation_model = m2m_info['relation']
                
                logger.info(f"[PASO 1/4] Importando tabla intermedia: {relation_table}")
                logger.info(f"[PASO 1/4] Campo: {field_name}, Modelo relacionado: {relation_model}")
                
                try:
                    m2m_file = self.export_m2m_table(relation_table, model, relation_model, 
                                                     source_model=model, field_name=field_name)
                    logger.info(f"[PASO 1/4] ✓ Tabla intermedia importada: {m2m_file}")
                except Exception as e:
                    logger.warning(f"[PASO 1/4] ⚠ No se pudo importar tabla intermedia {relation_table}: {e}")
                    logger.debug(f"[PASO 1/4] Error detallado: {e}")
        else:
            logger.info("[PASO 1/4] No se encontraron relaciones many2many desde fields_get")
            # Intentar detectar automáticamente desde los campos del modelo (método genérico)
            logger.debug(f"[PASO 1/4] Detectando relaciones many2many automáticamente desde campos para {model}...")
            auto_m2m = self._detect_m2m_from_fields(model, models_list)
            if auto_m2m:
                logger.info(f"[PASO 1/4] Detectadas {len(auto_m2m)} relaciones many2many automáticamente")
                for m2m_info in auto_m2m:
                    try:
                        m2m_file = self.export_m2m_table(
                            m2m_info['relation_table'],
                            model,
                            m2m_info['relation'],
                            source_model=model,
                            field_name=m2m_info['field_name']
                        )
                        logger.info(f"[PASO 1/4] ✓ Tabla intermedia importada: {m2m_file}")
                    except Exception as e:
                        logger.warning(f"[PASO 1/4] ⚠ No se pudo importar tabla intermedia {m2m_info['relation_table']}: {e}")
        
        # Cargar datos del JSON
        logger.info("[PASO 1/4] Cargando datos del archivo JSON...")
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        records = data.get('records', [])
        if not records:
            logger.warning(f"[ADVERTENCIA] No hay registros para migrar en {model}")
            return {'error': 'No hay registros'}
        
        logger.info(f"[PASO 1/4] ✓ Cargados {len(records)} registros desde JSON")
        
        # Consultar migration.tracking para ver qué registros ya están migrados
        logger.info("[PASO 1/4] Consultando registros ya migrados en migration.tracking...")
        existing_mapping = self.v18_conn.get_migration_mapping(model)
        existing_v13_ids = set(existing_mapping.keys())
        
        if existing_v13_ids:
            logger.info(f"[PASO 1/4] ✓ Encontrados {len(existing_v13_ids)} registros ya migrados")
        else:
            logger.info("[PASO 1/4] ✓ No hay registros migrados previamente")
        
        # PASO 2: Preparar datos para migración (filtrando los ya migrados)
        logger.info("[PASO 2/4] Preparando datos para migración...")
        fields_to_remove = ['id', 'create_uid', 'write_uid', 'create_date', 'write_date']
        
        records_to_migrate = []
        v13_ids = []
        skipped_count = 0
        
        for idx, record in enumerate(records, 1):
            v13_id = record.get('id')
            if not v13_id:
                continue
            
            # Verificar si ya está migrado
            v13_id_str = str(v13_id)
            if v13_id_str in existing_v13_ids:
                skipped_count += 1
                if idx % 1000 == 0:
                    logger.info(f"[PASO 2/4] Procesados {idx}/{len(records)} registros... (Omitidos: {skipped_count})")
                continue
            
            # Crear copia del registro sin campos no migrables
            # IMPORTANTE: No filtrar campos requeridos aunque sean None (se manejarán después)
            clean_record = {k: v for k, v in record.items() 
                          if k not in fields_to_remove}
            
            records_to_migrate.append(clean_record)
            v13_ids.append(v13_id)
            
            if idx % 1000 == 0:
                logger.info(f"[PASO 2/4] Procesados {idx}/{len(records)} registros... (Pendientes: {len(records_to_migrate)}, Omitidos: {skipped_count})")
        
        logger.info(f"[PASO 2/4] ✓ Total de registros preparados: {len(records_to_migrate)}")
        if skipped_count > 0:
            logger.info(f"[PASO 2/4] ✓ Registros ya migrados (omitidos): {skipped_count}")
        
        # Si no hay registros pendientes, terminar
        if not records_to_migrate:
            logger.info("=" * 80)
            logger.info(f"✓ TABLA {model} - TODOS LOS REGISTROS YA ESTÁN MIGRADOS")
            logger.info(f"  Total en v13: {v13_count}")
            logger.info(f"  Ya migrados: {len(existing_v13_ids)}")
            logger.info("  Pendientes: 0")
            logger.info("=" * 80)
            return {
                'created': 0,
                'skipped': skipped_count,
                'errors': 0,
                'total': len(records)
            }
        
        # PASO 3: Ordenar registros (sin parent primero si tiene parent_id)
        logger.info("[PASO 3/4] Ordenando registros...")
        has_parent = self.has_parent_id(model, self.v13_conn)
        
        if has_parent:
            logger.info("[PASO 3/4] Modelo tiene parent_id, ordenando registros (sin parent primero)...")
            records_to_migrate, v13_ids = self.sort_records_by_parent(records_to_migrate, v13_ids)
        else:
            logger.info("[PASO 3/4] Modelo no tiene parent_id")
        
        logger.info("[PASO 3/4] ✓ Ordenamiento completado")
        
        # Si tiene parent_id, procesar en dos fases:
        # 1. Primero los sin parent (en batches de 1000)
        # 2. Luego los con parent (en batches de 1000)
        if has_parent:
            # Separar registros sin parent y con parent
            records_without_parent = []
            ids_without_parent = []
            records_with_parent = []
            ids_with_parent = []
            
            for record, v13_id in zip(records_to_migrate, v13_ids):
                parent_id = record.get('parent_id', False)
                has_parent_value = False
                
                # Verificar si tiene parent_id en diferentes formatos:
                # 1. Como array/tupla [id, name] o [id] desde JSON
                # 2. Como número directo
                # 3. Como False o None (sin parent)
                if parent_id:
                    if isinstance(parent_id, (list, tuple)) and len(parent_id) > 0:
                        # Verificar que el primer elemento sea un ID válido (no False, None, o 0)
                        first_element = parent_id[0]
                        if first_element is not None and first_element is not False and first_element != 0:
                            has_parent_value = True
                    elif isinstance(parent_id, (int, str)) and parent_id and parent_id != 0:
                        # Es un número o string directo (y no es 0)
                        has_parent_value = True
                
                if has_parent_value:
                    records_with_parent.append(record)
                    ids_with_parent.append(v13_id)
                else:
                    records_without_parent.append(record)
                    ids_without_parent.append(v13_id)
            
            # Fase 1: Crear registros sin parent (en batches de 1000)
            if records_without_parent:
                logger.info(f"[PASO 4/4] Fase 1: Creando {len(records_without_parent)} registros sin parent_id (en batches de 1000)...")
                stats_without_parent = self._migrate_batches_with_mapping(
                    model, records_without_parent, ids_without_parent, 
                    allow_many2one, models_list, "sin parent"
                )
            else:
                stats_without_parent = {'created': 0, 'skipped': 0, 'errors': 0}
            
            # Esperar un momento para que se registre en migration.tracking (solo si no es modo test)
            if not self.test_mode:
                import time
                logger.info("[PASO 4/4] Esperando registro en migration.tracking...")
                time.sleep(1)
            else:
                logger.info("[PASO 4/4] [MODO TEST] No se espera registro en migration.tracking")
            
            # Fase 2: Mapear parent_id y many2one, luego crear registros con parent (en batches de 1000)
            if records_with_parent:
                logger.info(f"[PASO 4/4] Fase 2: Mapeando valores y creando {len(records_with_parent)} registros con parent_id (en batches de 1000)...")
                stats_with_parent = self._migrate_batches_with_mapping(
                    model, records_with_parent, ids_with_parent,
                    allow_many2one, models_list, "con parent", map_parent=True
                )
            else:
                stats_with_parent = {'created': 0, 'skipped': 0, 'errors': 0}
            
            # Combinar estadísticas
            stats = {
                'created': stats_without_parent.get('created', 0) + stats_with_parent.get('created', 0),
                'skipped': stats_without_parent.get('skipped', 0) + stats_with_parent.get('skipped', 0),
                'errors': stats_without_parent.get('errors', 0) + stats_with_parent.get('errors', 0),
                'total': len(records_to_migrate)
            }
            
            # Contar registros finales en migration.tracking
            logger.info("")
            logger.info("[CONTEO FINAL] Contando registros después de la migración...")
            v18_count_final = self.v18_conn.count_migration_tracking(model)
            logger.info(f"[CONTEO FINAL] ✓ Registros en migration.tracking (v18): {v18_count_final}")
            
            diferencia_final = v13_count - v18_count_final
            if diferencia_final > 0:
                logger.info(f"[CONTEO FINAL] ⚠ Faltan {diferencia_final} registros por migrar")
            elif diferencia_final < 0:
                logger.info(f"[CONTEO FINAL] ⚠ Hay {abs(diferencia_final)} registros más en v18 que en v13")
            else:
                logger.info("[CONTEO FINAL] ✓ Todos los registros están migrados")
            
            logger.info("=" * 80)
            logger.info(f"✓ TABLA {model} TERMINADA")
            logger.info(f"  Creados: {stats['created']}")
            logger.info(f"  Omitidos: {stats['skipped']}")
            logger.info(f"  Errores: {stats['errors']}")
            logger.info(f"  Total: {stats['total']}")
            logger.info(f"  Registros en v13: {v13_count}")
            logger.info(f"  Registros en v18: {v18_count_final}")
            logger.info("=" * 80)
            
            # Después de migrar sale.subscription.line, recalcular recurring_total en las subscripciones
            if model == 'sale.subscription.line':
                logger.info(f"[RECÁLCULO] Recalculando recurring_total en subscripciones después de migrar líneas...")
                try:
                    # Obtener todas las subscripciones que tienen líneas
                    lines = self.v18_conn.search_read('sale.subscription.line', [], ['sale_subscription_id'])
                    subscription_ids = set()
                    for line in lines:
                        sub_id = line.get('sale_subscription_id')
                        if isinstance(sub_id, list):
                            sub_id = sub_id[0] if sub_id else None
                        if sub_id:
                            subscription_ids.add(sub_id)
                    
                    subscription_ids_list = list(subscription_ids)
                    logger.info(f"[RECÁLCULO] Encontradas {len(subscription_ids_list)} subscripciones con líneas")
                    
                    # Recalcular en batches de 1000
                    batch_size = 1000
                    total_recalculated = 0
                    for i in range(0, len(subscription_ids_list), batch_size):
                        batch_ids = subscription_ids_list[i:i+batch_size]
                        
                        # Obtener stage_id actual de cada subscripción para mantenerlo
                        subs = self.v18_conn.search_read('sale.subscription', [('id', 'in', batch_ids)], ['id', 'stage_id'])
                        
                        # Agrupar por stage_id para actualizar en batch
                        by_stage = {}
                        for sub in subs:
                            stage_id = sub.get('stage_id')
                            if isinstance(stage_id, list):
                                stage_id = stage_id[0] if stage_id else None
                            if stage_id not in by_stage:
                                by_stage[stage_id] = []
                            by_stage[stage_id].append(sub['id'])
                        
                        # Hacer write con el mismo stage_id para forzar recálculo de recurring_total
                        for stage_id, ids in by_stage.items():
                            try:
                                self.v18_conn.models.execute_kw(
                                    self.v18_conn.db, self.v18_conn.uid, self.v18_conn.password,
                                    'sale.subscription', 'write',
                                    [ids, {'stage_id': stage_id}]
                                )
                                total_recalculated += len(ids)
                            except Exception as e:
                                logger.warning(f"[RECÁLCULO] Error recalculando batch de {len(ids)} subscripciones: {e}")
                        
                        if (i // batch_size + 1) % 5 == 0 or i + batch_size >= len(subscription_ids_list):
                            logger.info(f"[RECÁLCULO] Procesadas {min(i+batch_size, len(subscription_ids_list))}/{len(subscription_ids_list)} subscripciones...")
                    
                    logger.info(f"[RECÁLCULO] ✓ Recalculado recurring_total en {total_recalculated} subscripciones")
                except Exception as e:
                    logger.error(f"[RECÁLCULO] ✗ Error recalculando recurring_total: {e}")
                    import traceback
                    logger.debug(f"[RECÁLCULO] Traceback: {traceback.format_exc()}")
            
            # Actualizar mapeo de categorías UoM después de migrar uom.category
            if model == 'uom.category':
                logger.info("[ACTUALIZACIÓN] Actualizando mapeo de categorías UoM desde migration.tracking...")
                try:
                    new_mapping = self.v18_conn.get_migration_mapping('uom.category')
                    if new_mapping:
                        # Actualizar el mapeo existente con los nuevos valores
                        self.uom_category_mapping.update(new_mapping)
                        logger.info(f"[ACTUALIZACIÓN] ✓ Mapeo de categorías UoM actualizado: {len(self.uom_category_mapping)} mapeos totales")
                    else:
                        logger.warning("[ACTUALIZACIÓN] ⚠ No se encontró mapeo de categorías UoM en migration.tracking")
                except Exception as e:
                    logger.warning(f"[ACTUALIZACIÓN] ⚠ Error actualizando mapeo de categorías UoM: {e}")
            
            # NO migrar relaciones many2many aquí - se aplicarán después de que ambos modelos estén migrados
            # Las relaciones many2many se aplicarán al final cuando ambos modelos relacionados estén disponibles
            
            return stats
        
        # Si no tiene parent_id, crear todos los registros mapeando many2one durante la creación
        logger.info(f"[PASO 4/4] Creando {len(records_to_migrate)} registros...")
        stats = self._migrate_batches_with_mapping(
            model, records_to_migrate, v13_ids,
            allow_many2one, models_list
        )
        
        # Contar registros finales en migration.tracking
        logger.info("")
        logger.info("[CONTEO FINAL] Contando registros después de la migración...")
        v18_count_final = self.v18_conn.count_migration_tracking(model)
        logger.info(f"[CONTEO FINAL] ✓ Registros en migration.tracking (v18): {v18_count_final}")
        
        diferencia_final = v13_count - v18_count_final
        if diferencia_final > 0:
            logger.info(f"[CONTEO FINAL] ⚠ Faltan {diferencia_final} registros por migrar")
        elif diferencia_final < 0:
            logger.info(f"[CONTEO FINAL] ⚠ Hay {abs(diferencia_final)} registros más en v18 que en v13")
        else:
            logger.info("[CONTEO FINAL] ✓ Todos los registros están migrados")
        
        logger.info("=" * 80)
        logger.info(f"✓ TABLA {model} TERMINADA")
        logger.info(f"  Creados: {stats['created']}")
        logger.info(f"  Omitidos: {stats['skipped']}")
        logger.info(f"  Errores: {stats['errors']}")
        logger.info(f"  Total: {stats['total']}")
        logger.info(f"  Registros en v13: {v13_count}")
        logger.info(f"  Registros en v18: {v18_count_final}")
        logger.info("=" * 80)
        
        # Después de migrar sale.subscription.line, recalcular recurring_total en las subscripciones
        if model == 'sale.subscription.line':
            logger.info(f"[RECÁLCULO] Recalculando recurring_total en subscripciones después de migrar líneas...")
            try:
                # Obtener todas las subscripciones que tienen líneas
                lines = self.v18_conn.search_read('sale.subscription.line', [], ['sale_subscription_id'])
                subscription_ids = set()
                for line in lines:
                    sub_id = line.get('sale_subscription_id')
                    if isinstance(sub_id, list):
                        sub_id = sub_id[0] if sub_id else None
                    if sub_id:
                        subscription_ids.add(sub_id)
                
                subscription_ids_list = list(subscription_ids)
                logger.info(f"[RECÁLCULO] Encontradas {len(subscription_ids_list)} subscripciones con líneas")
                
                # Recalcular en batches de 1000
                batch_size = 1000
                total_recalculated = 0
                for i in range(0, len(subscription_ids_list), batch_size):
                    batch_ids = subscription_ids_list[i:i+batch_size]
                    
                    # Obtener stage_id actual de cada subscripción para mantenerlo
                    subs = self.v18_conn.search_read('sale.subscription', [('id', 'in', batch_ids)], ['id', 'stage_id'])
                    
                    # Agrupar por stage_id para actualizar en batch
                    by_stage = {}
                    for sub in subs:
                        stage_id = sub.get('stage_id')
                        if isinstance(stage_id, list):
                            stage_id = stage_id[0] if stage_id else None
                        if stage_id not in by_stage:
                            by_stage[stage_id] = []
                        by_stage[stage_id].append(sub['id'])
                    
                    # Hacer write con el mismo stage_id para forzar recálculo de recurring_total
                    for stage_id, ids in by_stage.items():
                        try:
                            self.v18_conn.models.execute_kw(
                                self.v18_conn.db, self.v18_conn.uid, self.v18_conn.password,
                                'sale.subscription', 'write',
                                [ids, {'stage_id': stage_id}]
                            )
                            total_recalculated += len(ids)
                        except Exception as e:
                            logger.warning(f"[RECÁLCULO] Error recalculando batch de {len(ids)} subscripciones: {e}")
                    
                    if (i // batch_size + 1) % 5 == 0 or i + batch_size >= len(subscription_ids_list):
                        logger.info(f"[RECÁLCULO] Procesadas {min(i+batch_size, len(subscription_ids_list))}/{len(subscription_ids_list)} subscripciones...")
                
                logger.info(f"[RECÁLCULO] ✓ Recalculado recurring_total en {total_recalculated} subscripciones")
            except Exception as e:
                logger.error(f"[RECÁLCULO] ✗ Error recalculando recurring_total: {e}")
                import traceback
                logger.debug(f"[RECÁLCULO] Traceback: {traceback.format_exc()}")
        
        # Actualizar mapeo de categorías UoM después de migrar uom.category
        if model == 'uom.category':
            logger.info("[ACTUALIZACIÓN] Actualizando mapeo de categorías UoM desde migration.tracking...")
            try:
                new_mapping = self.v18_conn.get_migration_mapping('uom.category')
                if new_mapping:
                    # Actualizar el mapeo existente con los nuevos valores
                    self.uom_category_mapping.update(new_mapping)
                    logger.info(f"[ACTUALIZACIÓN] ✓ Mapeo de categorías UoM actualizado: {len(self.uom_category_mapping)} mapeos totales")
                else:
                    logger.warning("[ACTUALIZACIÓN] ⚠ No se encontró mapeo de categorías UoM en migration.tracking")
            except Exception as e:
                logger.warning(f"[ACTUALIZACIÓN] ⚠ Error actualizando mapeo de categorías UoM: {e}")
        
        # NO migrar relaciones many2many aquí - se aplicarán después de que ambos modelos estén migrados
        # Las relaciones many2many se aplicarán al final cuando ambos modelos relacionados estén disponibles
        
        return stats
    
    def _migrate_batches_with_mapping(self, model: str, records_to_migrate: List[Dict], 
                                     v13_ids: List[int], allow_many2one: bool,
                                     models_list: List[str] = None, phase: str = "",
                                     map_parent: bool = False) -> Dict[str, Any]:
        """
        Migra registros en batches, mapeando valores antes de cada batch.
        
        Args:
            model: Nombre del modelo
            records_to_migrate: Lista de registros a migrar
            v13_ids: Lista de IDs v13 correspondientes
            allow_many2one: Si True, mapea campos many2one
            models_list: Lista de modelos a migrar (para mapear dependencias)
            phase: Fase de migración (para logging)
            map_parent: Si True, mapea parent_id
        
        Returns:
            Diccionario con estadísticas
        """
        # Tamaño de batch estándar
        batch_size = self.batch_size
        
        # Actualizar mapeo de categorías UoM antes de procesar uom.uom
        if model == 'uom.uom':
            logger.info("[ACTUALIZACIÓN] Actualizando mapeo de categorías UoM desde migration.tracking...")
            try:
                tracking_mapping = self.v18_conn.get_migration_mapping('uom.category')
                if tracking_mapping:
                    # Actualizar el mapeo existente con los nuevos valores
                    self.uom_category_mapping.update(tracking_mapping)
                    logger.info(f"[ACTUALIZACIÓN] ✓ Mapeo de categorías UoM actualizado: {len(self.uom_category_mapping)} mapeos totales")
                else:
                    logger.warning("[ACTUALIZACIÓN] ⚠ No se encontró mapeo de categorías UoM en migration.tracking")
            except Exception as e:
                logger.warning(f"[ACTUALIZACIÓN] ⚠ Error actualizando mapeo de categorías UoM: {e}")
        
        # Cargar mapeo de pricelist desde migration.tracking antes de procesar sale.subscription
        # Esto es necesario porque sale.subscription necesita mapear pricelist_id desde v13
        if model == 'sale.subscription' and not self.pricelist_mapping:
            logger.info("[ACTUALIZACIÓN] Cargando mapeo de product.pricelist desde migration.tracking...")
            try:
                self.pricelist_mapping = self.v18_conn.get_migration_mapping('product.pricelist')
                if self.pricelist_mapping:
                    logger.info(f"[ACTUALIZACIÓN] ✓ Mapeo de product.pricelist cargado: {len(self.pricelist_mapping)} mapeos totales")
                else:
                    logger.warning("[ACTUALIZACIÓN] ⚠ No se encontró mapeo de product.pricelist en migration.tracking")
            except Exception as e:
                logger.warning(f"[ACTUALIZACIÓN] ⚠ Error cargando mapeo de product.pricelist: {e}")
        
        # Cargar mapeo de sale.subscription desde migration.tracking antes de procesar sale.subscription.line
        # Esto es necesario porque sale.subscription.line necesita mapear contract_id a sale_subscription_id
        if model == 'sale.subscription.line':
            logger.info("[ACTUALIZACIÓN] Cargando mapeo de sale.subscription desde migration.tracking...")
            try:
                subscription_mapping = self.v18_conn.get_migration_mapping('sale.subscription')
                if subscription_mapping:
                    logger.info(f"[ACTUALIZACIÓN] ✓ Mapeo de sale.subscription cargado: {len(subscription_mapping)} suscripciones disponibles")
                    logger.info(f"[ACTUALIZACIÓN] Este mapeo se usará para asociar contract_id (v13) -> sale_subscription_id (v18) en las líneas")
                else:
                    logger.error("[ACTUALIZACIÓN] ✗ CRÍTICO: No se encontró mapeo de sale.subscription en migration.tracking")
                    logger.error("[ACTUALIZACIÓN] Las líneas de suscripción NO se podrán asociar a suscripciones sin este mapeo")
            except Exception as e:
                logger.error(f"[ACTUALIZACIÓN] ✗ Error cargando mapeo de sale.subscription: {e}")
                logger.error("[ACTUALIZACIÓN] Las líneas de suscripción NO se podrán asociar a suscripciones sin este mapeo")
        
        total_batches = (len(records_to_migrate) + batch_size - 1) // batch_size
        stats = {
            'created': 0,
            'skipped': 0,
            'errors': 0,
            'total': len(records_to_migrate)
        }
        
        phase_text = f" ({phase})" if phase else ""
        logger.info(f"[CREACIÓN{phase_text}] Total de batches: {total_batches} (tamaño: {batch_size} registros por batch)")
        
        for i in range(0, len(records_to_migrate), batch_size):
            batch_num = (i // batch_size) + 1
            batch_records = records_to_migrate[i:i + batch_size]
            batch_v13_ids = v13_ids[i:i + batch_size]
            
            logger.info(f"[CREACIÓN{phase_text}] Batch {batch_num}/{total_batches} en proceso ({len(batch_records)} registros)...")
            
            # VERIFICACIÓN INICIAL: Asegurar que batch_records y batch_v13_ids tengan la misma longitud
            if len(batch_records) != len(batch_v13_ids):
                logger.error(f"[ERROR] Desajuste inicial: {len(batch_records)} registros vs {len(batch_v13_ids)} IDs")
                # Ajustar para que coincidan
                min_len = min(len(batch_records), len(batch_v13_ids))
                batch_records = batch_records[:min_len]
                batch_v13_ids = batch_v13_ids[:min_len]
                logger.warning(f"[ERROR] Ajustados a {min_len} registros/IDs")
            
            # Mapear valores antes de crear el batch
            logger.info(f"[MAPEO{phase_text}] Mapeando valores para batch {batch_num}/{total_batches}...")
            
            # Mapear many2one si está permitido
            if allow_many2one and models_list:
                batch_records = self.map_many2one_ids(batch_records, model, models_list)
                # Verificar que no se hayan filtrado registros
                if len(batch_records) != len(batch_v13_ids):
                    logger.error(f"[ERROR] Desajuste después de map_many2one_ids: {len(batch_records)} registros vs {len(batch_v13_ids)} IDs")
                    min_len = min(len(batch_records), len(batch_v13_ids))
                    batch_records = batch_records[:min_len]
                    batch_v13_ids = batch_v13_ids[:min_len]
            
            # Mapear parent_id si es necesario
            if map_parent:
                batch_records = self.map_parent_id(batch_records, model)
                # Verificar que no se hayan filtrado registros
                if len(batch_records) != len(batch_v13_ids):
                    logger.error(f"[ERROR] Desajuste después de map_parent_id: {len(batch_records)} registros vs {len(batch_v13_ids)} IDs")
                    min_len = min(len(batch_records), len(batch_v13_ids))
                    batch_records = batch_records[:min_len]
                    batch_v13_ids = batch_v13_ids[:min_len]
            
            logger.info(f"[MAPEO{phase_text}] ✓ Valores mapeados para batch {batch_num}/{total_batches}")
            
            # Log de verificación: mostrar valores mapeados de campos críticos antes de preparar
            if batch_records and len(batch_records) > 0:
                first_record = batch_records[0]
                critical_fields = ['user_id', 'partner_id', 'team_id', 'parent_id', 'sale_subscription_id', 'contract_id']
                for field in critical_fields:
                    if field in first_record:
                        logger.info(f"[VERIFICACIÓN POST-MAPEO] Primer registro, {field}={first_record[field]} (tipo: {type(first_record[field])})")
                # Verificación especial para sale.subscription.line
                if model == 'sale.subscription.line':
                    if 'sale_subscription_id' in first_record:
                        logger.info(f"[VERIFICACIÓN POST-MAPEO] ✓ sale_subscription_id encontrado en primer registro: {first_record['sale_subscription_id']}")
                    else:
                        logger.warning(f"[VERIFICACIÓN POST-MAPEO] ⚠ sale_subscription_id NO encontrado en primer registro después de map_many2one_ids")
                    if 'contract_id' in first_record:
                        logger.warning(f"[VERIFICACIÓN POST-MAPEO] ⚠ contract_id todavía presente en primer registro después de map_many2one_ids (debería haberse eliminado)")
            
            # Preparar registros para creación (validar campos, limpiar datos inválidos)
            logger.info(f"[PREPARACIÓN{phase_text}] Preparando registros para creación en batch {batch_num}/{total_batches}...")
            prepared_data = self.prepare_records_for_creation(batch_records, model, models_list)
            
            # Extraer registros preparados y campos many2many
            batch_records_prepared = []
            batch_m2m_data = []  # Lista de dicts con v13_id y m2m_fields
            batch_uom_name_changes = []  # Lista de cambios de nombre de uom para registrar
            
            for prep_data in prepared_data:
                record = prep_data['record']
                batch_records_prepared.append(record)
                
                # Extraer cambios de nombre de uom si existen
                if '_uom_name_changes' in record:
                    for change in record['_uom_name_changes']:
                        batch_uom_name_changes.append({
                            'v13_id': change['v13_id'],
                            'v18_id': change['v18_id'],
                            'v13_name': change['v13_name'],
                            'v18_name': change['v18_name'],
                            'field': change['field'],
                            'model_v13_id': prep_data.get('v13_id')  # ID del registro que usa esta uom
                        })
                    # Eliminar el campo temporal del registro
                    del record['_uom_name_changes']
                
                if prep_data.get('m2m_fields'):
                    batch_m2m_data.append({
                        'v13_id': prep_data.get('v13_id'),
                        'm2m_fields': prep_data['m2m_fields']
                    })
            
            batch_records = batch_records_prepared
            
            # Verificar que prepare_records_for_creation no haya filtrado registros
            if len(batch_records) != len(batch_v13_ids):
                logger.error(f"[ERROR] Desajuste después de prepare_records_for_creation: {len(batch_records)} registros vs {len(batch_v13_ids)} IDs")
                min_len = min(len(batch_records), len(batch_v13_ids))
                batch_records = batch_records[:min_len]
                batch_v13_ids = batch_v13_ids[:min_len]
                logger.warning(f"[ERROR] Ajustados a {min_len} registros/IDs después de preparación")
            
            # VERIFICACIÓN CRÍTICA: Asegurar que todos los registros tengan 'name' válido
            try:
                v18_model_fields = self.v18_conn.get_fields(model)
                has_name_field = 'name' in v18_model_fields
            except Exception as e:
                # Si no se pueden obtener campos, asumir que el modelo tiene 'name' si es res.partner
                has_name_field = (model == 'res.partner')
                if not has_name_field:
                    logger.warning(f"[VERIFICACIÓN] No se pudieron obtener campos de {model} para verificar 'name': {e}")
            
            if model == 'res.partner' or has_name_field:
                for idx, record in enumerate(batch_records):
                    name_value = record.get('name')
                    record_id = batch_v13_ids[idx] if idx < len(batch_v13_ids) else 'Unknown'
                    
                    # Verificar si name está vacío o no existe
                    is_name_empty = (name_value is None or 
                                   name_value is False or 
                                   (isinstance(name_value, str) and not name_value.strip()))
                    
                    if is_name_empty:
                        # Forzar asignación de name
                        if model == 'res.partner':
                            # Intentar usar display_name como fallback
                            display_name = record.get('display_name')
                            
                            if display_name and isinstance(display_name, str) and display_name.strip():
                                record['name'] = display_name
                            else:
                                # Para res.partner, usar espacio en blanco si no hay nombre
                                record['name'] = " "
                        else:
                            record['name'] = f"{model} {record_id}"
                        logger.warning(f"  ⚠ [VERIFICACIÓN CRÍTICA] Registro {idx+1} en batch {batch_num} tenía 'name' vacío (ID v13: {record_id}), forzado a: {record['name']}")
                    else:
                        # Verificar que name no sea solo espacios
                        if isinstance(name_value, str) and not name_value.strip():
                            # Para res.partner, usar espacio en blanco si no hay nombre
                            record['name'] = " " if model == 'res.partner' else f"{model} {record_id}"
                            logger.warning(f"  ⚠ [VERIFICACIÓN CRÍTICA] Registro {idx+1} en batch {batch_num} tenía 'name' solo espacios (ID v13: {record_id}), forzado a: {record['name']}")
            
            logger.info(f"[PREPARACIÓN{phase_text}] ✓ Registros preparados para batch {batch_num}/{total_batches}")
            
            # VERIFICACIÓN CRÍTICA: Asegurar que batch_records y batch_v13_ids tengan la misma longitud
            if len(batch_records) != len(batch_v13_ids):
                logger.error(f"[ERROR CRÍTICO] Desajuste entre registros e IDs: {len(batch_records)} registros vs {len(batch_v13_ids)} IDs")
                logger.error("[ERROR CRÍTICO] Esto no debería pasar. Ajustando IDs para que coincidan...")
                # Ajustar batch_v13_ids para que coincida con batch_records
                batch_v13_ids = batch_v13_ids[:len(batch_records)]
                logger.warning(f"[ERROR CRÍTICO] IDs ajustados a {len(batch_v13_ids)} para coincidir con {len(batch_records)} registros")
            
            # VERIFICACIÓN FINAL ABSOLUTA: Asegurar que 'name' esté presente y válido ANTES de enviar a migrate_batch
            if model == 'res.partner':
                for idx, record in enumerate(batch_records):
                    if 'name' not in record or not record.get('name') or (isinstance(record.get('name'), str) and not record.get('name').strip()):
                        v13_id = batch_v13_ids[idx] if idx < len(batch_v13_ids) else 'Unknown'
                        # Forzar asignación de name
                        display_name = record.get('display_name')
                        
                        if display_name and isinstance(display_name, str) and display_name.strip():
                            record['name'] = display_name
                        else:
                            # Para res.partner, usar espacio en blanco si no hay nombre
                            record['name'] = " "
                        logger.error(f"  ✗✗✗ [VERIFICACIÓN FINAL ABSOLUTA] Registro {idx+1} en batch {batch_num} NO tenía 'name' válido (ID v13: {v13_id}), FORZADO a: '{record['name']}'")
            
            # VERIFICACIÓN FINAL ANTES DE LLAMAR A migrate_batch
            if len(batch_records) != len(batch_v13_ids):
                logger.error(f"[ERROR CRÍTICO FINAL] Desajuste antes de migrate_batch: {len(batch_records)} registros vs {len(batch_v13_ids)} IDs")
                logger.error("[ERROR CRÍTICO FINAL] Esto causará un error en migrate_batch. Ajustando...")
                # Ajustar para que coincidan (tomar el mínimo)
                min_len = min(len(batch_records), len(batch_v13_ids))
                if len(batch_records) > min_len:
                    logger.warning(f"[ERROR CRÍTICO FINAL] Reduciendo batch_records de {len(batch_records)} a {min_len}")
                    batch_records = batch_records[:min_len]
                if len(batch_v13_ids) > min_len:
                    logger.warning(f"[ERROR CRÍTICO FINAL] Reduciendo batch_v13_ids de {len(batch_v13_ids)} a {min_len}")
                    batch_v13_ids = batch_v13_ids[:min_len]
                logger.warning(f"[ERROR CRÍTICO FINAL] Ajustados a {min_len} registros/IDs")
            
            # VERIFICACIÓN FINAL: Asegurar que todos los registros sean diccionarios válidos
            valid_batch_records = []
            valid_batch_v13_ids = []
            for idx, (record, v13_id) in enumerate(zip(batch_records, batch_v13_ids)):
                if not isinstance(record, dict):
                    logger.error(f"[ERROR] Registro {idx+1} en batch {batch_num} no es un diccionario: {type(record)} - {record}")
                    stats['errors'] += 1
                    self._log_failed_record(model, v13_id, record, f"Registro no es un diccionario: {type(record)}", batch_num, total_batches)
                    continue
                # Verificar que el diccionario no esté vacío
                if not record:
                    logger.error(f"[ERROR] Registro {idx+1} en batch {batch_num} es un diccionario vacío (ID v13: {v13_id})")
                    stats['errors'] += 1
                    self._log_failed_record(model, v13_id, record, "Registro es un diccionario vacío", batch_num, total_batches)
                    continue
                valid_batch_records.append(record)
                valid_batch_v13_ids.append(v13_id)
            
            # Actualizar batch_records y batch_v13_ids con los registros válidos
            if len(valid_batch_records) != len(batch_records):
                logger.warning(f"[VALIDACIÓN] {len(batch_records) - len(valid_batch_records)} registros inválidos filtrados del batch {batch_num}")
                batch_records = valid_batch_records
                batch_v13_ids = valid_batch_v13_ids
            
            # Si no hay registros válidos, saltar este batch
            if not batch_records:
                logger.warning(f"[VALIDACIÓN] No hay registros válidos en batch {batch_num}, saltando...")
                continue
            
            # VERIFICACIÓN FINAL: Limpiar y validar todos los valores en cada registro antes de enviar
            cleaned_batch_records = []
            for idx, record in enumerate(batch_records):
                cleaned_record = {}
                v13_id = batch_v13_ids[idx] if idx < len(batch_v13_ids) else 'Unknown'
                
                for field_name, field_value in record.items():
                    # Asegurar que el valor sea serializable para XML-RPC
                    if field_value is None:
                        # Omitir valores None (Odoo no los acepta bien en algunos casos)
                        continue
                    elif isinstance(field_value, bool):
                        # Mantener booleanos (True/False son válidos en XML-RPC)
                        cleaned_record[field_name] = field_value
                    elif isinstance(field_value, (int, float)):
                        # Mantener números (incluyendo 0)
                        cleaned_record[field_name] = field_value
                    elif isinstance(field_value, str):
                        # Mantener strings (incluyendo strings vacíos)
                        cleaned_record[field_name] = field_value
                    elif field_value is False:
                        # False explícito (diferente de None) - mantenerlo
                        cleaned_record[field_name] = False
                    elif isinstance(field_value, list):
                        # Listas solo si están vacías o contienen tipos válidos
                        if len(field_value) == 0:
                            continue  # Omitir listas vacías
                        elif all(isinstance(item, (int, str, bool, float)) for item in field_value):
                            # Lista de tipos simples, omitir (no debería estar aquí en campos simples)
                            logger.debug(f"[LIMPIEZA] Campo {field_name} tiene lista de valores simples, omitiendo")
                            continue
                        else:
                            # Lista compleja, omitir
                            logger.warning(f"[LIMPIEZA] Campo {field_name} tiene lista compleja, omitiendo")
                            continue
                    elif isinstance(field_value, dict):
                        # Diccionarios no son válidos en campos simples
                        logger.warning(f"[LIMPIEZA] Campo {field_name} tiene diccionario, omitiendo")
                        continue
                    else:
                        # Tipo desconocido, omitir
                        logger.warning(f"[LIMPIEZA] Campo {field_name} tiene tipo desconocido {type(field_value)}, omitiendo")
                        continue
                
                # Verificar que el registro limpio no esté vacío
                if not cleaned_record:
                    logger.error(f"[LIMPIEZA] Registro {idx+1} quedó vacío después de limpieza (ID v13: {v13_id})")
                    logger.error(f"[LIMPIEZA] Registro original tenía {len(record)} campos: {list(record.keys())[:10]}")
                    logger.error(f"[LIMPIEZA] Tipos de valores originales: {[(k, type(v).__name__) for k, v in list(record.items())[:10]]}")
                    stats['errors'] += 1
                    self._log_failed_record(model, batch_v13_ids[idx] if idx < len(batch_v13_ids) else 0, record, "Registro quedó vacío después de limpieza", batch_num, total_batches)
                    continue
                
                # Verificación adicional: asegurar que el registro sea un diccionario válido
                try:
                    # Intentar serializar a JSON para verificar que es válido
                    import json
                    json.dumps(cleaned_record)
                except (TypeError, ValueError) as e:
                    logger.error(f"[LIMPIEZA] Registro {idx+1} no es serializable (ID v13: {v13_id}): {e}")
                    logger.error(f"[LIMPIEZA] Contenido del registro: {cleaned_record}")
                    stats['errors'] += 1
                    self._log_failed_record(model, batch_v13_ids[idx] if idx < len(batch_v13_ids) else 0, record, f"Registro no serializable: {e}", batch_num, total_batches)
                    continue
                
                # Log del registro limpio para debugging (solo para crm.team)
                if model == 'crm.team' and idx < 2:
                    logger.debug(f"[LIMPIEZA] Registro {idx+1} limpio (ID v13: {v13_id}): {json.dumps(cleaned_record, indent=2, ensure_ascii=False)}")
                
                cleaned_batch_records.append(cleaned_record)
            
            # Actualizar batch_records con los registros limpios
            if len(cleaned_batch_records) != len(batch_records):
                logger.warning(f"[LIMPIEZA] {len(batch_records) - len(cleaned_batch_records)} registros filtrados después de limpieza")
                # Ajustar batch_v13_ids también
                batch_v13_ids = batch_v13_ids[:len(cleaned_batch_records)]
                batch_records = cleaned_batch_records
            
            # Si no hay registros después de la limpieza, saltar
            if not batch_records:
                logger.warning(f"[LIMPIEZA] No hay registros válidos después de limpieza en batch {batch_num}, saltando...")
                continue
            
            # Crear el batch
            batch_id = f"{model}_{batch_num}_{total_batches}"
            
            if self.test_mode:
                logger.info(f"[MODO TEST] Simulando migración de {len(batch_records)} registros (NO se crearán en v18)")
                stats['created'] += len(batch_records)
                logger.info(f"[MODO TEST] Batch {batch_num}/{total_batches} simulado - "
                          f"Simulados: {len(batch_records)}, "
                          f"Omitidos: 0, "
                          f"Errores: 0")
            else:
                # Inicializar final_batch_records fuera del try para que esté disponible en el except
                final_batch_records = []
                
                try:
                    # Conversión final explícita de tipos para XML-RPC
                    # Asegurar que todos los valores sean tipos nativos de Python válidos para XML-RPC
                    for record in batch_records:
                        final_record = {}
                        for field_name, field_value in record.items():
                            # Convertir explícitamente a tipos válidos para XML-RPC
                            if field_value is None:
                                # Omitir None
                                continue
                            elif isinstance(field_value, bool):
                                # Mantener booleanos
                                final_record[field_name] = bool(field_value)
                            elif isinstance(field_value, (int, float)):
                                # Mantener números
                                final_record[field_name] = int(field_value) if isinstance(field_value, float) and field_value.is_integer() else field_value
                            elif isinstance(field_value, str):
                                # Mantener strings
                                final_record[field_name] = str(field_value)
                            elif field_value is False:
                                # False explícito (ya es bool)
                                final_record[field_name] = False
                            elif isinstance(field_value, (list, tuple, dict)):
                                # Estructuras complejas no son válidas para XML-RPC en create()
                                logger.warning(f"[CONVERSIÓN FINAL] Campo {field_name} tiene tipo complejo {type(field_value)}, omitiendo")
                                continue
                            else:
                                # Cualquier otro tipo, intentar convertir a string o omitir
                                logger.warning(f"[CONVERSIÓN FINAL] Campo {field_name} tiene tipo {type(field_value)}, intentando convertir")
                                try:
                                    final_record[field_name] = str(field_value)
                                except Exception as conv_error:
                                    logger.warning(f"[CONVERSIÓN FINAL] No se pudo convertir {field_name} ({type(field_value)}), omitiendo: {conv_error}")
                                    continue
                        
                        if final_record:
                            final_batch_records.append(final_record)
                    
                    if not final_batch_records:
                        logger.warning(f"[CONVERSIÓN FINAL] No hay registros válidos después de conversión final en batch {batch_num}, saltando...")
                        continue
                    
                    # Ajustar batch_v13_ids si es necesario
                    if len(final_batch_records) != len(batch_v13_ids):
                        logger.warning(f"[CONVERSIÓN FINAL] Ajustando batch_v13_ids de {len(batch_v13_ids)} a {len(final_batch_records)}")
                        batch_v13_ids = batch_v13_ids[:len(final_batch_records)]
                    
                    # LOGS DETALLADOS ANTES DE ENVIAR A migrate_batch
                    logger.info(f"[DEBUG MIGRATE_BATCH] Preparando para enviar batch {batch_num}/{total_batches} a migrate_batch")
                    logger.info(f"[DEBUG MIGRATE_BATCH] Modelo: {model}")
                    logger.info(f"[DEBUG MIGRATE_BATCH] Número de registros: {len(final_batch_records)}")
                    logger.info(f"[DEBUG MIGRATE_BATCH] Número de v13_ids: {len(batch_v13_ids)}")
                    logger.info(f"[DEBUG MIGRATE_BATCH] batch_id: {batch_id}")
                    
                    # Verificar que todos los registros sean diccionarios válidos
                    for idx, record in enumerate(final_batch_records):
                        if not isinstance(record, dict):
                            logger.error(f"[DEBUG MIGRATE_BATCH] ✗ Registro {idx+1} NO es un diccionario: {type(record)}")
                            logger.error(f"[DEBUG MIGRATE_BATCH] Contenido: {record}")
                        else:
                            # Log del primer registro completo para debugging
                            if idx == 0:
                                import json
                                logger.info(f"[DEBUG MIGRATE_BATCH] Primer registro (v13_id={batch_v13_ids[0] if batch_v13_ids else 'N/A'}):")
                                logger.info(f"[DEBUG MIGRATE_BATCH] {json.dumps(record, indent=2, ensure_ascii=False, default=str)}")
                            
                            # Verificar tipos de valores
                            invalid_fields = []
                            for field_name, field_value in record.items():
                                if not isinstance(field_value, (str, int, float, bool, type(None))):
                                    invalid_fields.append(f"{field_name}: {type(field_value)}")
                            
                            if invalid_fields:
                                logger.warning(f"[DEBUG MIGRATE_BATCH] Registro {idx+1} tiene campos con tipos inválidos: {', '.join(invalid_fields)}")
                    
                    # Verificar que batch_v13_ids sean enteros
                    invalid_ids = []
                    for idx, v13_id in enumerate(batch_v13_ids):
                        if not isinstance(v13_id, (int, str)):
                            invalid_ids.append(f"Índice {idx}: {type(v13_id)}")
                    
                    if invalid_ids:
                        logger.warning(f"[DEBUG MIGRATE_BATCH] batch_v13_ids tiene tipos inválidos: {', '.join(invalid_ids)}")
                    
                    logger.info("[DEBUG MIGRATE_BATCH] Llamando a migrate_batch...")
                    logger.info(f"[PROGRESO] Enviando {len(final_batch_records)} registros a Odoo (esto puede tardar varios segundos)...")
                    
                    import time
                    start_time = time.time()
                    
                    try:
                        # Log antes de la llamada
                        logger.debug(f"[DEBUG MIGRATE_BATCH] Antes de execute_kw - timestamp: {time.time()}")
                        
                        result = self.v18_conn.migrate_batch(
                            model,
                            final_batch_records,
                            batch_v13_ids,
                            batch_id
                        )
                        
                        # Log inmediatamente después de recibir la respuesta
                        logger.debug(f"[DEBUG MIGRATE_BATCH] Después de execute_kw - timestamp: {time.time()}")
                        logger.debug(f"[DEBUG MIGRATE_BATCH] Resultado recibido, tipo: {type(result)}")
                        
                        elapsed_time = time.time() - start_time
                        logger.info(f"[PROGRESO] ✓ migrate_batch completado en {elapsed_time:.2f} segundos")
                        
                        # Verificar que result no sea None
                        if result is None:
                            logger.error("[PROGRESO] ✗ ERROR CRÍTICO: migrate_batch retornó None")
                            raise ValueError("migrate_batch retornó None - esto no debería pasar")
                        
                        # Mostrar estadísticas del resultado
                        if isinstance(result, dict):
                            created_count = result.get('stats', {}).get('created', 0)
                            skipped_count = result.get('stats', {}).get('skipped', 0)
                            errors_count = result.get('stats', {}).get('errors', 0)
                            logger.info(f"[PROGRESO] Resultado: ✓ {created_count} creados, ⊘ {skipped_count} omitidos, ✗ {errors_count} errores")
                            
                            # Verificar que stats exista
                            if 'stats' not in result:
                                logger.warning(f"[PROGRESO] ⚠ Resultado no tiene 'stats', estructura: {list(result.keys())}")
                        else:
                            logger.error(f"[PROGRESO] ✗ ERROR: Resultado no es un diccionario: {type(result)}")
                            logger.error(f"[PROGRESO] Contenido: {result}")
                            raise ValueError(f"migrate_batch retornó un tipo inesperado: {type(result)}")
                        
                        # Log después de procesar el resultado
                        logger.debug(f"[DEBUG MIGRATE_BATCH] Resultado procesado correctamente, continuando al siguiente batch...")
                        
                        # Registrar cambios de nombre de uom en migration.tracking
                        if batch_uom_name_changes:
                            self._register_uom_name_changes(batch_uom_name_changes, batch_id)
                        
                        # Log adicional para verificar que el resultado se procesó
                        logger.info(f"[PROGRESO] ✓ Batch {batch_num}/{total_batches} procesado exitosamente")
                    except Exception as migrate_error:
                        # Log detallado del error
                        error_str = str(migrate_error)
                        logger.error("[DEBUG MIGRATE_BATCH] ✗ Error en migrate_batch:")
                        logger.error(f"[DEBUG MIGRATE_BATCH] Tipo de error: {type(migrate_error)}")
                        logger.error(f"[DEBUG MIGRATE_BATCH] Mensaje: {error_str}")
                        
                        # Log de los primeros 3 registros para debugging
                        import json
                        logger.error("[DEBUG MIGRATE_BATCH] Primeros 3 registros que se intentaron enviar:")
                        for idx in range(min(3, len(final_batch_records))):
                            logger.error(f"[DEBUG MIGRATE_BATCH] Registro {idx+1} (v13_id={batch_v13_ids[idx] if idx < len(batch_v13_ids) else 'N/A'}):")
                            logger.error(f"[DEBUG MIGRATE_BATCH] {json.dumps(final_batch_records[idx], indent=2, ensure_ascii=False, default=str)}")
                        
                        # Log de batch_v13_ids
                        logger.error(f"[DEBUG MIGRATE_BATCH] batch_v13_ids: {batch_v13_ids[:min(5, len(batch_v13_ids))]}")
                        
                        # Re-lanzar el error para que se maneje normalmente
                        raise
                    
                    # Verificar que result sea válido antes de procesar
                    if result is None:
                        logger.error(f"[CREACIÓN{phase_text}] ✗ ERROR CRÍTICO: result es None después de migrate_batch en batch {batch_num}")
                        stats['errors'] += len(batch_records)
                        logger.info(f"[PROGRESO] Continuando al siguiente batch ({batch_num + 1}/{total_batches})...")
                        continue  # Continuar con el siguiente batch
                    
                    if not isinstance(result, dict):
                        logger.error(f"[CREACIÓN{phase_text}] ✗ ERROR CRÍTICO: result no es un diccionario en batch {batch_num}: {type(result)}")
                        stats['errors'] += len(batch_records)
                        logger.info(f"[PROGRESO] Continuando al siguiente batch ({batch_num + 1}/{total_batches})...")
                        continue  # Continuar con el siguiente batch
                    
                    batch_stats = result.get('stats', {})
                    if not batch_stats:
                        logger.warning(f"[CREACIÓN{phase_text}] ⚠ Resultado no tiene 'stats' en batch {batch_num}, usando valores por defecto")
                        batch_stats = {'created': 0, 'skipped': 0, 'errors': len(batch_records)}
                    
                    stats['created'] += batch_stats.get('created', 0)
                    stats['skipped'] += batch_stats.get('skipped', 0)
                    stats['errors'] += batch_stats.get('errors', 0)
                    
                    logger.info(f"[CREACIÓN{phase_text}] Batch {batch_num}/{total_batches} completado - "
                              f"Creados: {batch_stats.get('created', 0)}, "
                              f"Omitidos: {batch_stats.get('skipped', 0)}, "
                              f"Errores: {batch_stats.get('errors', 0)}")
                    
                    # Log para confirmar que se está continuando al siguiente batch
                    if batch_num < total_batches:
                        logger.info(f"[PROGRESO] Continuando al siguiente batch ({batch_num + 1}/{total_batches})...")
                    
                    # NO aplicar relaciones many2many aquí - se aplicarán después de que ambos modelos estén migrados
                    # Guardar información para aplicar después
                    if batch_m2m_data:
                        logger.debug(f"[M2M BATCH] {len(batch_m2m_data)} registros con campos many2many guardados para aplicar después de migrar ambos modelos")
                    
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"[ERROR] Error en batch {batch_num}/{total_batches}: {error_msg}")
                    
                    # Verificar si el error es por duplicados (login duplicado en res.users)
                    is_duplicate_error = False
                    if model == 'res.users' and ('login' in error_msg.lower() or 'duplicado' in error_msg.lower() or 'mismo inicio' in error_msg.lower()):
                        is_duplicate_error = True
                        logger.warning("[DUPLICADO] Error de usuario duplicado detectado, buscando usuarios existentes y creando migration.tracking...")
                    
                    # Si es error de duplicado en res.users, buscar usuarios existentes y crear tracking
                    if is_duplicate_error:
                        for idx, (record, v13_id) in enumerate(zip(batch_records, batch_v13_ids)):
                            login = record.get('login')
                            if not login:
                                stats['errors'] += 1
                                logger.error(f"[ERROR INDIVIDUAL] Registro {idx+1} (ID v13: {v13_id}) no tiene login, omitiendo")
                                try:
                                    self._log_failed_record(model, v13_id, record, "Registro no tiene login", batch_num, total_batches)
                                except Exception as log_error:
                                    logger.error(f"[ERROR] No se pudo guardar registro fallido en archivo de errores: {log_error}")
                                continue
                            
                            try:
                                # Buscar el usuario existente por login en v18
                                search_domain = [['login', '=', login]]
                                existing_users = self.v18_conn.search_read(
                                    'res.users',
                                    search_domain,
                                    ['id', 'login'],
                                    limit=1
                                )
                                
                                if existing_users and len(existing_users) > 0:
                                    v18_id = existing_users[0]['id']
                                    
                                    # Verificar si ya existe el tracking para este v13_id
                                    tracking_domain = [
                                        ['model_name', '=', model],
                                        ['v13_id', '=', v13_id]
                                    ]
                                    existing_tracking = self.v18_conn.search_read(
                                        'migration.tracking',
                                        tracking_domain,
                                        ['id', 'v18_id'],
                                        limit=1
                                    )
                                    
                                    if existing_tracking:
                                        # Ya existe tracking, solo loguear
                                        logger.info(f"[DUPLICADO] Usuario v13_id={v13_id} (login='{login}') ya tiene tracking -> v18_id={existing_tracking[0]['v18_id']}")
                                        stats['skipped'] += 1
                                    else:
                                        # Crear registro en migration.tracking
                                        tracking_data = {
                                            'name': f"{model} - V13:{v13_id} -> V18:{v18_id} (duplicado)",
                                            'model_name': model,
                                            'v13_id': v13_id,
                                            'v18_id': v18_id,
                                            'batch_id': batch_id,
                                            'status': 'skipped',
                                            'delete_v18_on_unlink': False,
                                        }
                                        
                                        try:
                                            created_tracking_id = self.v18_conn.models.execute_kw(
                                                self.v18_conn.db, self.v18_conn.uid, self.v18_conn.password,
                                                'migration.tracking', 'create',
                                                [[tracking_data]]
                                            )
                                            logger.info(f"[DUPLICADO] ✓ Usuario v13_id={v13_id} (login='{login}') ya existe en v18 (v18_id={v18_id}), creado tracking: {created_tracking_id}")
                                            stats['skipped'] += 1
                                        except Exception as tracking_error:
                                            logger.error(f"[ERROR] No se pudo crear tracking para usuario duplicado v13_id={v13_id}: {tracking_error}")
                                            stats['errors'] += 1
                                            try:
                                                self._log_failed_record(model, v13_id, record, f"Error creando tracking: {tracking_error}", batch_num, total_batches)
                                            except Exception as log_error:
                                                logger.error(f"[ERROR] No se pudo guardar registro fallido en archivo de errores: {log_error}")
                                else:
                                    # No se encontró el usuario, esto es extraño si el error dice que es duplicado
                                    logger.warning(f"[DUPLICADO] ⚠ Usuario v13_id={v13_id} (login='{login}') no encontrado en v18, pero el error indica duplicado. Intentando crear individualmente...")
                                    try:
                                        # Intentar crear individualmente por si acaso
                                        individual_result = self.v18_conn.migrate_batch(
                                            model,
                                            [record],
                                            [v13_id],
                                            f"{batch_id}_ind_{idx}"
                                        )
                                        individual_stats = individual_result.get('stats', {})
                                        stats['created'] += individual_stats.get('created', 0)
                                        stats['skipped'] += individual_stats.get('skipped', 0)
                                        stats['errors'] += individual_stats.get('errors', 0)
                                    except Exception as individual_error:
                                        stats['errors'] += 1
                                        individual_error_msg = str(individual_error)
                                        logger.error(f"[ERROR INDIVIDUAL] Registro {idx+1} (ID v13: {v13_id}) falló: {individual_error_msg}")
                                        try:
                                            self._log_failed_record(model, v13_id, record, individual_error_msg, batch_num, total_batches)
                                        except Exception as log_error:
                                            logger.error(f"[ERROR] No se pudo guardar registro fallido en archivo de errores: {log_error}")
                            except Exception as search_error:
                                stats['errors'] += 1
                                search_error_msg = str(search_error)
                                logger.error(f"[ERROR] Error buscando usuario duplicado v13_id={v13_id} (login='{login}'): {search_error_msg}")
                                try:
                                    self._log_failed_record(model, v13_id, record, f"Error buscando usuario duplicado: {search_error_msg}", batch_num, total_batches)
                                except Exception as log_error:
                                    logger.error(f"[ERROR] No se pudo guardar registro fallido en archivo de errores: {log_error}")
                    else:
                        # Log detallado de cada registro del batch que falló
                        logger.error(f"[ERROR DETALLADO] Batch completo falló - Modelo: {model}, Batch: {batch_num}/{total_batches}")
                        logger.error(f"[ERROR DETALLADO] Error: {error_msg}")
                        
                        # Usar final_batch_records si está disponible, sino batch_records
                        # Intentar obtener final_batch_records del scope del try
                        try:
                            records_to_log = final_batch_records
                            logger.debug(f"[ERROR DETALLADO] Usando final_batch_records: {len(records_to_log)} registros")
                        except NameError:
                            try:
                                records_to_log = batch_records
                                logger.debug(f"[ERROR DETALLADO] Usando batch_records: {len(records_to_log)} registros")
                            except NameError:
                                logger.error("[ERROR DETALLADO] No se encontraron registros para loguear (ni final_batch_records ni batch_records disponibles)")
                                records_to_log = []
                        
                        ids_to_log = batch_v13_ids
                        
                        if len(records_to_log) != len(ids_to_log):
                            logger.warning(f"[ERROR DETALLADO] Desajuste: {len(records_to_log)} registros vs {len(ids_to_log)} IDs, ajustando...")
                            min_len = min(len(records_to_log), len(ids_to_log))
                            records_to_log = records_to_log[:min_len]
                            ids_to_log = ids_to_log[:min_len]
                        
                        logger.error(f"[ERROR DETALLADO] Registros en el batch: {len(records_to_log)}")
                        
                        # Guardar información de cada registro del batch
                        import json
                        for idx, (record, v13_id) in enumerate(zip(records_to_log, ids_to_log)):
                            stats['errors'] += 1
                            
                            # Log de los primeros 3 registros del batch para no saturar
                            if idx < 3:
                                key_fields = ['name', 'id', 'parent_id', 'category_id', 'email', 'vat', 'team_id', 'user_id']
                                record_summary = {k: v for k, v in record.items() if k in key_fields}
                                logger.error(f"[ERROR DETALLADO] Registro {idx+1} (v13_id={v13_id}): {json.dumps(record_summary, indent=2, ensure_ascii=False)}")
                            
                            # Guardar en archivo de errores (usar self, no self.v18_conn)
                            try:
                                # Asegurar que v13_id sea un entero
                                v13_id_int = int(v13_id) if isinstance(v13_id, (str, float)) else v13_id
                                if not isinstance(v13_id_int, int):
                                    logger.warning(f"[ERROR] v13_id no es un entero válido: {v13_id} (tipo: {type(v13_id)})")
                                    v13_id_int = 0  # Usar 0 como fallback
                                
                                # Asegurar que record sea un diccionario
                                if not isinstance(record, dict):
                                    logger.warning(f"[ERROR] record no es un diccionario: {type(record)}")
                                    record = {'error': 'Registro no válido', 'original_type': str(type(record))}
                                
                                self._log_failed_record(model, v13_id_int, record, error_msg, batch_num, total_batches)
                                logger.debug(f"[ERROR LOG] Error guardado para {model} v13_id={v13_id_int}")
                            except Exception as log_error:
                                logger.error(f"[ERROR] No se pudo guardar registro fallido en archivo de errores: {log_error}")
                                logger.error(f"[ERROR] Detalles del error de logging: {type(log_error)} - {log_error}")
                                logger.error(f"[ERROR] Modelo: {model}, v13_id: {v13_id}, tipo: {type(v13_id)}")
                                logger.error(f"[ERROR] Record tipo: {type(record)}")
                                import traceback
                                logger.error(f"[ERROR] Traceback: {traceback.format_exc()}")
                        
                        if len(records_to_log) > 3:
                            logger.error(f"[ERROR DETALLADO] ... y {len(records_to_log) - 3} registros más (ver archivo errors/errors_{model.replace('.', '_')}.json para detalles completos)")
        
        logger.info(f"[CREACIÓN{phase_text}] ✓ Todos los batches completados")
        return stats
    
    def _wait_for_migration_tracking(self, model: str, v13_ids: List[int], max_attempts: int = 10, wait_seconds: float = 0.5):
        """
        Espera consultando la DB hasta que los registros estén disponibles en migration.tracking.
        
        Args:
            model: Nombre del modelo
            v13_ids: Lista de IDs v13 a verificar
            max_attempts: Número máximo de intentos
            wait_seconds: Segundos a esperar entre intentos
        """
        import time
        
        if not v13_ids:
            return
        
        logger.debug(f"[M2M WAIT] Esperando a que {len(v13_ids)} registros estén en migration.tracking para {model}...")
        
        for attempt in range(1, max_attempts + 1):
            # Obtener mapeo actual consultando la DB
            model_mapping = self.v18_conn.get_migration_mapping(model)
            
            if model_mapping:
                # Verificar cuántos IDs están disponibles
                found_count = 0
                for v13_id in v13_ids:
                    v13_id_str = str(v13_id)
                    if v13_id_str in model_mapping:
                        found_count += 1
                
                if found_count == len(v13_ids):
                    logger.debug(f"[M2M WAIT] ✓ Todos los registros están disponibles en migration.tracking (intento {attempt})")
                    return
                else:
                    logger.debug(f"[M2M WAIT] Intento {attempt}/{max_attempts}: {found_count}/{len(v13_ids)} registros disponibles")
            else:
                logger.debug(f"[M2M WAIT] Intento {attempt}/{max_attempts}: No se encontró mapeo para {model}")
            
            if attempt < max_attempts:
                time.sleep(wait_seconds)
        
        logger.warning(f"[M2M WAIT] ⚠ No todos los registros están disponibles después de {max_attempts} intentos")
    
    def _apply_m2m_fields_batch(self, model: str, batch_m2m_data: List[Dict], batch_v13_ids: List[int]):
        """
        Aplica campos many2many a los registros recién creados usando write.
        
        Args:
            model: Nombre del modelo
            batch_m2m_data: Lista de dicts con v13_id y m2m_fields
            batch_v13_ids: Lista de IDs v13 del batch
        """
        if not batch_m2m_data:
            logger.debug(f"[M2M BATCH] No hay datos many2many para aplicar en {model}")
            return
        
        logger.info(f"[M2M BATCH] Procesando {len(batch_m2m_data)} registros con campos many2many para {model}")
        
        # Obtener mapeo de v13_id -> v18_id para este modelo
        # Ya debería estar disponible porque esperamos con _wait_for_migration_tracking
        model_mapping = self.v18_conn.get_migration_mapping(model)
        
        if not model_mapping:
            logger.error(f"[M2M BATCH] No se encontró mapeo para {model}, no se pueden aplicar campos many2many")
            return
        
        logger.info(f"[M2M BATCH] Mapeo cargado para {model}: {len(model_mapping)} registros")
        
        # Estadísticas: contar relaciones que deberían existir
        total_expected_relations = 0
        relations_by_field = {}  # Para contar por campo
        
        # Agrupar campos many2many por registro
        records_to_update = {}
        skipped_count = 0
        
        for m2m_item in batch_m2m_data:
            v13_id = m2m_item.get('v13_id')
            if not v13_id:
                skipped_count += 1
                logger.debug("[M2M BATCH] Item sin v13_id, omitiendo")
                continue
            
            v13_id_str = str(v13_id)
            if v13_id_str not in model_mapping:
                skipped_count += 1
                logger.warning(f"[M2M BATCH] ⚠ No se encontró mapeo para v13_id={v13_id} en {model}, omitiendo")
                continue
            
            v18_id = model_mapping[v13_id_str]
            m2m_fields = m2m_item.get('m2m_fields', {})
            
            if m2m_fields:
                if v18_id not in records_to_update:
                    records_to_update[v18_id] = {}
                
                # Aplicar cada campo many2many usando comando [(6, 0, [ids])]
                for field_name, mapped_ids in m2m_fields.items():
                    if mapped_ids and len(mapped_ids) > 0:
                        records_to_update[v18_id][field_name] = [(6, 0, mapped_ids)]
                        # Contar relaciones esperadas
                        total_expected_relations += len(mapped_ids)
                        if field_name not in relations_by_field:
                            relations_by_field[field_name] = 0
                        relations_by_field[field_name] += len(mapped_ids)
                        logger.info(f"[M2M BATCH] ✓ Campo {field_name} para {model} ID v18={v18_id} (v13_id={v13_id}): {len(mapped_ids)} IDs mapeados")
                    else:
                        logger.warning(f"[M2M BATCH] ⚠ Campo {field_name} para {model} ID v18={v18_id} tiene lista vacía, omitiendo")
        
        if skipped_count > 0:
            logger.warning(f"[M2M BATCH] ⚠ Se omitieron {skipped_count} registros por falta de mapeo")
        
        # Mostrar estadísticas de relaciones esperadas
        logger.info(f"[M2M BATCH] 📊 Relaciones esperadas: {total_expected_relations} total")
        for field_name, count in relations_by_field.items():
            logger.info(f"[M2M BATCH]   - {field_name}: {count} relaciones")
        
        # Aplicar actualizaciones en batches
        if records_to_update:
            logger.info(f"[M2M BATCH] Aplicando campos many2many a {len(records_to_update)} registros...")
            
            # Convertir a lista de tuplas (id, values) para write
            write_data = []
            for v18_id, values in records_to_update.items():
                write_data.append((v18_id, values))
            
            # Aplicar en batches de 100
            batch_size = 100
            success_count = 0
            error_count = 0
            total_relations_applied = 0  # Contar relaciones aplicadas exitosamente
            
            for i in range(0, len(write_data), batch_size):
                batch = write_data[i:i + batch_size]
                try:
                    # Usar write individual para cada registro
                    for v18_id, values in batch:
                        try:
                            # Usar execute_kw directamente para write
                            self.v18_conn.models.execute_kw(
                                self.v18_conn.db, self.v18_conn.uid, self.v18_conn.password,
                                model, 'write',
                                [[v18_id], values]
                            )
                            success_count += 1
                            # Contar relaciones aplicadas (sumar todos los IDs en todos los campos)
                            for field_name, field_value in values.items():
                                if isinstance(field_value, list) and len(field_value) > 0:
                                    # field_value es [(6, 0, [ids])]
                                    if len(field_value) == 3 and field_value[0] == 6:
                                        ids_list = field_value[2]
                                        if isinstance(ids_list, list):
                                            total_relations_applied += len(ids_list)
                        except Exception as e2:
                            error_count += 1
                            logger.error(f"[M2M BATCH] ✗ Error aplicando campos many2many a {model} ID v18={v18_id}: {e2}")
                            logger.error(f"[M2M BATCH] Valores intentados: {values}")
                    
                    logger.info(f"[M2M BATCH] Batch {i//batch_size + 1}: {len(batch)} registros procesados")
                except Exception as e:
                    logger.error(f"[M2M BATCH] Error en batch {i//batch_size + 1}: {e}")
                    error_count += len(batch)
            
            # Mostrar estadísticas finales
            logger.info(f"[M2M BATCH] ✓ Completado: {success_count} registros actualizados exitosamente, {error_count} errores de {len(write_data)} totales")
            logger.info(f"[M2M BATCH] 📊 Relaciones aplicadas: {total_relations_applied} de {total_expected_relations} esperadas")
            if total_expected_relations > 0:
                percentage = (total_relations_applied / total_expected_relations) * 100
                logger.info(f"[M2M BATCH] 📊 Porcentaje de éxito: {percentage:.2f}%")
                if total_relations_applied < total_expected_relations:
                    missing = total_expected_relations - total_relations_applied
                    logger.warning(f"[M2M BATCH] ⚠ Faltan {missing} relaciones por aplicar")
            else:
                logger.warning("[M2M BATCH] ⚠ No se esperaban relaciones many2many")
        else:
            logger.warning("[M2M BATCH] ⚠ No hay registros para actualizar después del procesamiento")
    
    def _migrate_many2many_relations(self, model: str, models_list: List[str] = None):
        """
        Migra relaciones many2many DESPUÉS de que ambos modelos relacionados estén migrados.
        Este método debe llamarse después de que todos los modelos estén migrados.
        
        Args:
            model: Nombre del modelo
            models_list: Lista de modelos a migrar
        """
        logger.info("")
        logger.info("=" * 80)
        logger.info(f"MIGRANDO RELACIONES MANY2MANY PARA: {model}")
        logger.info("=" * 80)
        
        # Obtener todas las relaciones many2many de este modelo (solo las que están en models_list)
        m2m_tables = self.get_many2many_tables(model, self.v13_conn, models_list)
        
        # También verificar relaciones conocidas
        known_m2m = self._check_known_many2many(model, models_list) if models_list else []
        
        # Combinar ambas listas (evitar duplicados)
        all_m2m = m2m_tables.copy()
        for known in known_m2m:
            if not any(m['relation_table'] == known['relation_table'] for m in all_m2m):
                all_m2m.append(known)
        
        if not all_m2m:
            logger.info("[M2M REL] No se encontraron relaciones many2many para migrar")
            logger.info("=" * 80)
            return
        
        logger.info(f"[M2M REL] Encontradas {len(all_m2m)} relaciones many2many para migrar")
        
        # Obtener mapeo de IDs para este modelo
        model_mapping = self.v18_conn.get_migration_mapping(model)
        if not model_mapping:
            logger.warning(f"[M2M REL] No se encontró mapeo para {model}, no se pueden migrar relaciones")
            logger.info("=" * 80)
            return
        
        logger.info(f"[M2M REL] Mapeo cargado para {model}: {len(model_mapping)} registros")
        
        for m2m_info in all_m2m:
            field_name = m2m_info['field_name']
            relation_table = m2m_info['relation_table']
            relation_model = m2m_info['relation']
            
            # Verificar que el modelo relacionado esté en models_list
            if models_list and relation_model not in models_list:
                logger.debug(f"[M2M REL] Saltando relación {field_name} -> {relation_model} (no está en models_to_migrate.txt)")
                continue
            
            logger.info("")
            logger.info(f"[M2M REL] Procesando relación: {field_name} -> {relation_model}")
            logger.info(f"[M2M REL] Tabla intermedia: {relation_table}")
            
            # Obtener mapeo para el modelo relacionado
            relation_mapping = self.v18_conn.get_migration_mapping(relation_model)
            if not relation_mapping:
                logger.warning(f"[M2M REL] No se encontró mapeo para {relation_model}, saltando relación")
                continue
            
            logger.info(f"[M2M REL] Mapeo cargado para {relation_model}: {len(relation_mapping)} registros")
            
            # Cargar datos de la tabla intermedia
            m2m_file = self.get_import_filepath_m2m(model, relation_model)
            
            if not os.path.exists(m2m_file):
                logger.warning(f"[M2M REL] Archivo no encontrado: {m2m_file}, saltando relación")
                continue
            
            try:
                with open(m2m_file, 'r', encoding='utf-8') as f:
                    m2m_data = json.load(f)
                
                m2m_records = m2m_data.get('records', [])
                if not m2m_records:
                    logger.info(f"[M2M REL] No hay registros en {m2m_file}, saltando relación")
                    continue
                
                logger.info(f"[M2M REL] Cargados {len(m2m_records)} registros de relación")
                
                # Determinar nombres de campos en la tabla intermedia
                model1_field = model.replace('.', '_') + '_id'
                model2_field = relation_model.replace('.', '_') + '_id'
                
                # Verificar qué campo corresponde a qué modelo
                sample_record = m2m_records[0] if m2m_records else {}
                actual_model1_field = None
                actual_model2_field = None
                
                for key in sample_record.keys():
                    if key.endswith('_id') and key != 'id':
                        if model1_field in key or key.startswith(model.split('.')[0]):
                            actual_model1_field = key
                        elif model2_field in key or key.startswith(relation_model.split('.')[0]):
                            actual_model2_field = key
                
                # Si no se encontraron, usar los construidos
                if not actual_model1_field:
                    actual_model1_field = model1_field
                if not actual_model2_field:
                    actual_model2_field = model2_field
                
                logger.info(f"[M2M REL] Campos identificados: {actual_model1_field} -> {actual_model2_field}")
                
                # Agrupar relaciones por registro del modelo principal
                relations_by_record = {}
                
                for m2m_record in m2m_records:
                    v13_model1_id = m2m_record.get(actual_model1_field)
                    v13_model2_id = m2m_record.get(actual_model2_field)
                    
                    if not v13_model1_id or not v13_model2_id:
                        continue
                    
                    # Mapear IDs
                    v13_model1_id_str = str(v13_model1_id)
                    v13_model2_id_str = str(v13_model2_id)
                    
                    v18_model1_id = model_mapping.get(v13_model1_id_str)
                    v18_model2_id = relation_mapping.get(v13_model2_id_str)
                    
                    if not v18_model1_id or not v18_model2_id:
                        continue
                    
                    # Agrupar por registro del modelo principal
                    if v18_model1_id not in relations_by_record:
                        relations_by_record[v18_model1_id] = []
                    
                    if v18_model2_id not in relations_by_record[v18_model1_id]:
                        relations_by_record[v18_model1_id].append(v18_model2_id)
                
                logger.info(f"[M2M REL] Relaciones agrupadas: {len(relations_by_record)} registros con relaciones")
                
                if not relations_by_record:
                    logger.warning("[M2M REL] No se pudieron mapear relaciones, saltando")
                    continue
                
                # Contar relaciones esperadas
                total_expected_relations = 0
                for related_ids in relations_by_record.values():
                    total_expected_relations += len(related_ids)
                
                logger.info(f"[M2M REL] 📊 Relaciones esperadas para {field_name}: {total_expected_relations} total")
                logger.info(f"[M2M REL] 📊 Registros con relaciones: {len(relations_by_record)}")
                
                # Aplicar relaciones en batches
                total_relations_applied = 0
                batch_size = 100
                records_list = list(relations_by_record.items())
                
                for i in range(0, len(records_list), batch_size):
                    batch = records_list[i:i + batch_size]
                    batch_num = (i // batch_size) + 1
                    total_batches = (len(records_list) + batch_size - 1) // batch_size
                    
                    logger.info(f"[M2M REL] Procesando batch {batch_num}/{total_batches} ({len(batch)} registros)...")
                    
                    if self.test_mode:
                        for v18_id, related_ids in batch:
                            total_relations_applied += len(related_ids)
                        logger.info(f"[M2M REL] [MODO TEST] Simuladas {len(batch)} actualizaciones de relaciones")
                    else:
                        try:
                            # Actualizar relaciones usando write
                            for v18_id, related_ids in batch:
                                try:
                                    # Usar write para actualizar el campo many2many
                                    # En Odoo, many2many se actualiza con [(6, 0, [ids])]
                                    self.v18_conn.models.execute_kw(
                                        self.v18_conn.db, self.v18_conn.uid, self.v18_conn.password,
                                        model, 'write',
                                        [[v18_id], {field_name: [(6, 0, related_ids)]}]
                                    )
                                    total_relations_applied += len(related_ids)
                                except Exception as e:
                                    logger.warning(f"[M2M REL] Error actualizando relaciones para {model} ID {v18_id}: {e}")
                            
                            logger.info(f"[M2M REL] Batch {batch_num}/{total_batches} completado")
                        except Exception as e:
                            logger.error(f"[M2M REL] Error en batch {batch_num}: {e}")
                
                # Mostrar estadísticas finales
                logger.info(f"[M2M REL] ✓ Relación {field_name} migrada: {total_relations_applied} relaciones aplicadas")
                logger.info(f"[M2M REL] 📊 Relaciones aplicadas: {total_relations_applied} de {total_expected_relations} esperadas")
                if total_expected_relations > 0:
                    percentage = (total_relations_applied / total_expected_relations) * 100
                    logger.info(f"[M2M REL] 📊 Porcentaje de éxito: {percentage:.2f}%")
                    if total_relations_applied < total_expected_relations:
                        missing = total_expected_relations - total_relations_applied
                        logger.warning(f"[M2M REL] ⚠ Faltan {missing} relaciones por aplicar")
                else:
                    logger.warning(f"[M2M REL] ⚠ No se esperaban relaciones para {field_name}")
                
            except Exception as e:
                logger.error(f"[M2M REL] Error procesando relación {field_name}: {e}")
                import traceback
                logger.debug(f"[M2M REL] Traceback: {traceback.format_exc()}")
        
        logger.info("=" * 80)
        logger.info(f"✓ RELACIONES MANY2MANY PARA {model} COMPLETADAS")
        logger.info("=" * 80)
    
    def _apply_m2m_from_imports(self, model: str, models_list: List[str] = None):
        """
        Aplica relaciones many2many desde los imports (campos que vienen como arrays simples).
        Este método procesa los campos many2many que se guardaron durante la preparación.
        
        Args:
            model: Nombre del modelo
            models_list: Lista de modelos a migrar
        """
        logger.info("")
        logger.info("=" * 80)
        logger.info(f"APLICANDO RELACIONES MANY2MANY DESDE IMPORTS PARA: {model}")
        logger.info("=" * 80)
        
        # Cargar datos del import
        json_file = self.get_import_filepath(model)
        if not os.path.exists(json_file):
            logger.info(f"[M2M IMPORT] No se encontró archivo de import para {model}, saltando")
            return
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                import_data = json.load(f)
            
            records = import_data.get('records', [])
            if not records:
                logger.info(f"[M2M IMPORT] No hay registros en {json_file}, saltando")
                return
            
            logger.info(f"[M2M IMPORT] Cargados {len(records)} registros desde {json_file}")
            
            # Obtener campos many2many del modelo
            v18_fields = self.v18_conn.get_fields(model)
            m2m_fields_to_process = {}
            
            # Obtener lista de campos many2many permitidos para este modelo
            allowed_m2m_fields = self.m2m_fields_config.get(model, [])
            
            if not allowed_m2m_fields:
                logger.info(f"[M2M IMPORT] No hay campos many2many configurados para {model} en m2m_fields.json, saltando")
                logger.info("[M2M IMPORT] Para procesar campos many2many, agregue la configuración en exceptions/m2m_fields.json")
                return
            
            # Filtrar solo los campos permitidos
            for field_name, field_info in v18_fields.items():
                if field_info.get('type') == 'many2many':
                    # Verificar que el campo esté en la lista de permitidos
                    if field_name not in allowed_m2m_fields:
                        logger.debug(f"[M2M IMPORT] Campo {field_name} omitido (no está en m2m_fields.json)")
                        continue
                    
                    relation_model = field_info.get('relation', '')
                    if relation_model and models_list and relation_model in models_list:
                        m2m_fields_to_process[field_name] = relation_model
                    else:
                        logger.debug(f"[M2M IMPORT] Campo {field_name} omitido (modelo relacionado {relation_model} no está en models_to_migrate.txt)")
            
            if not m2m_fields_to_process:
                logger.info(f"[M2M IMPORT] No se encontraron campos many2many válidos para procesar en {model}")
                logger.info(f"[M2M IMPORT] Campos permitidos: {allowed_m2m_fields}")
                return
            
            logger.info(f"[M2M IMPORT] Campos many2many a procesar: {list(m2m_fields_to_process.keys())}")
            
            # Obtener mapeo del modelo principal
            model_mapping = self.v18_conn.get_migration_mapping(model)
            if not model_mapping:
                logger.warning(f"[M2M IMPORT] No se encontró mapeo para {model}, saltando")
                return
            
            # Procesar cada campo many2many
            total_expected = 0
            total_applied = 0
            
            for field_name, relation_model in m2m_fields_to_process.items():
                logger.info(f"[M2M IMPORT] Procesando campo {field_name} -> {relation_model}")
                
                # Obtener mapeo del modelo relacionado
                relation_mapping = self.v18_conn.get_migration_mapping(relation_model)
                if not relation_mapping:
                    logger.warning(f"[M2M IMPORT] ⚠ No se encontró mapeo para {relation_model}, saltando {field_name}")
                    continue
                
                # Agrupar relaciones por registro
                records_to_update = {}
                field_expected = 0
                
                for record in records:
                    v13_id = record.get('id')
                    if not v13_id:
                        continue
                    
                    v13_id_str = str(v13_id)
                    if v13_id_str not in model_mapping:
                        continue
                    
                    v18_id = model_mapping[v13_id_str]
                    
                    # Obtener campo many2many del import (puede venir como array simple)
                    field_value = record.get(field_name)
                    if not field_value or not isinstance(field_value, list):
                        continue
                    
                    # Mapear IDs de v13 a v18
                    mapped_ids = []
                    for v13_rel_id in field_value:
                        if isinstance(v13_rel_id, (int, str)):
                            v13_rel_id_str = str(v13_rel_id)
                            if v13_rel_id_str in relation_mapping:
                                mapped_ids.append(relation_mapping[v13_rel_id_str])
                    
                    if mapped_ids:
                        if v18_id not in records_to_update:
                            records_to_update[v18_id] = {}
                        records_to_update[v18_id][field_name] = [(6, 0, mapped_ids)]
                        field_expected += len(mapped_ids)
                
                total_expected += field_expected
                logger.info(f"[M2M IMPORT] {field_name}: {field_expected} relaciones esperadas para {len(records_to_update)} registros")
                
                # Aplicar relaciones en batches
                if records_to_update:
                    field_applied = 0
                    records_list = list(records_to_update.items())
                    batch_size = 1000
                    total_batches = (len(records_list) + batch_size - 1) // batch_size
                    
                    logger.info(f"[M2M IMPORT] Aplicando relaciones en {total_batches} batches de {batch_size} registros...")
                    
                    for i in range(0, len(records_list), batch_size):
                        batch = records_list[i:i + batch_size]
                        batch_num = (i // batch_size) + 1
                        
                        logger.info(f"[M2M IMPORT] Procesando batch {batch_num}/{total_batches} ({len(batch)} registros)...")
                        
                        if self.test_mode:
                            # En modo test, solo contar
                            for v18_id, values in batch:
                                for field_val in values.values():
                                    if isinstance(field_val, list) and len(field_val) == 3 and field_val[0] == 6:
                                        field_applied += len(field_val[2])
                            logger.info(f"[M2M IMPORT] [MODO TEST] Batch {batch_num}/{total_batches} simulado")
                        else:
                            # Verificar que los registros existan en migration.tracking antes de aplicar
                            verified_batch = []
                            for v18_id, values in batch:
                                # Verificar que el registro existe en migration.tracking
                                tracking_domain = [['v18_id', '=', v18_id]]
                                tracking_count = self.v18_conn.count_migration_tracking(model, tracking_domain)
                                
                                if tracking_count > 0:
                                    verified_batch.append((v18_id, values))
                                else:
                                    logger.warning(f"[M2M IMPORT] ⚠ Registro {model} ID v18={v18_id} no encontrado en migration.tracking, omitiendo")
                            
                            if not verified_batch:
                                logger.warning(f"[M2M IMPORT] ⚠ Batch {batch_num}/{total_batches} sin registros verificados, saltando")
                                continue
                            
                            # Aplicar relaciones del batch
                            batch_applied = 0
                            for v18_id, values in verified_batch:
                                try:
                                    # Verificar si las relaciones ya existen antes de aplicar
                                    # Leer el registro actual en v18 para verificar relaciones existentes
                                    current_record = self.v18_conn.search_read(
                                        model,
                                        [['id', '=', v18_id]],
                                        list(values.keys()),
                                        limit=1
                                    )
                                    
                                    if current_record and len(current_record) > 0:
                                        current_data = current_record[0]
                                        needs_update = False
                                        updated_values = {}
                                        
                                        # Verificar cada campo many2many
                                        for field_name_check, expected_ids in values.items():
                                            # expected_ids es [(6, 0, [ids])]
                                            if isinstance(expected_ids, list) and len(expected_ids) == 3 and expected_ids[0] == 6:
                                                expected_ids_list = expected_ids[2] if isinstance(expected_ids[2], list) else []
                                                
                                                # Obtener IDs actuales del registro
                                                current_ids = current_data.get(field_name_check, [])
                                                if isinstance(current_ids, list):
                                                    # Si current_ids contiene tuplas [id, name], extraer solo los IDs
                                                    current_ids_list = [item[0] if isinstance(item, (list, tuple)) and len(item) > 0 else item for item in current_ids]
                                                else:
                                                    current_ids_list = []
                                                
                                                # Convertir a sets para comparar
                                                expected_set = set(expected_ids_list)
                                                current_set = set(current_ids_list)
                                                
                                                # Verificar si faltan relaciones
                                                missing_ids = expected_set - current_set
                                                if missing_ids:
                                                    # Hay relaciones faltantes, actualizar
                                                    # Combinar IDs existentes con los faltantes
                                                    final_ids = list(current_set | expected_set)
                                                    updated_values[field_name_check] = [(6, 0, final_ids)]
                                                    needs_update = True
                                                    logger.debug(f"[M2M IMPORT] Registro {model} ID v18={v18_id} campo {field_name_check}: faltan {len(missing_ids)} relaciones, actualizando...")
                                                else:
                                                    # Todas las relaciones ya existen
                                                    logger.debug(f"[M2M IMPORT] Registro {model} ID v18={v18_id} campo {field_name_check}: todas las relaciones ya existen, omitiendo")
                                        
                                        # Solo actualizar si hay cambios
                                        if needs_update and updated_values:
                                            self.v18_conn.models.execute_kw(
                                                self.v18_conn.db, self.v18_conn.uid, self.v18_conn.password,
                                                model, 'write',
                                                [[v18_id], updated_values]
                                            )
                                            # Contar relaciones aplicadas (solo las nuevas, no todas)
                                            for field_name_check, field_val in updated_values.items():
                                                if isinstance(field_val, list) and len(field_val) == 3 and field_val[0] == 6:
                                                    # Contar solo las relaciones nuevas (las que faltaban)
                                                    expected_ids_list = values.get(field_name_check, [])
                                                    if isinstance(expected_ids_list, list) and len(expected_ids_list) == 3 and expected_ids_list[0] == 6:
                                                        expected_set = set(expected_ids_list[2]) if isinstance(expected_ids_list[2], list) else set()
                                                        current_ids_list = current_data.get(field_name_check, [])
                                                        if isinstance(current_ids_list, list):
                                                            current_ids_clean = [item[0] if isinstance(item, (list, tuple)) and len(item) > 0 else item for item in current_ids_list]
                                                        else:
                                                            current_ids_clean = []
                                                        current_set = set(current_ids_clean)
                                                        missing_count = len(expected_set - current_set)
                                                        batch_applied += missing_count
                                        elif not needs_update:
                                            # Todas las relaciones ya existen, no hacer nada
                                            logger.debug(f"[M2M IMPORT] Registro {model} ID v18={v18_id}: todas las relaciones ya existen, omitiendo")
                                    else:
                                        # No se pudo leer el registro, intentar aplicar de todas formas
                                        logger.warning(f"[M2M IMPORT] ⚠ No se pudo leer registro {model} ID v18={v18_id}, intentando aplicar relaciones...")
                                        self.v18_conn.models.execute_kw(
                                            self.v18_conn.db, self.v18_conn.uid, self.v18_conn.password,
                                            model, 'write',
                                            [[v18_id], values]
                                        )
                                        # Contar relaciones aplicadas
                                        for field_val in values.values():
                                            if isinstance(field_val, list) and len(field_val) == 3 and field_val[0] == 6:
                                                batch_applied += len(field_val[2])
                                except Exception as e:
                                    logger.error(f"[M2M IMPORT] Error aplicando {field_name} a {model} ID v18={v18_id}: {e}")
                            
                            field_applied += batch_applied
                            logger.info(f"[M2M IMPORT] ✓ Batch {batch_num}/{total_batches} completado: {batch_applied} relaciones aplicadas")
                    
                    total_applied += field_applied
                    logger.info(f"[M2M IMPORT] ✓ {field_name}: {field_applied} relaciones aplicadas de {field_expected} esperadas")
            
            logger.info(f"[M2M IMPORT] 📊 Total: {total_applied} de {total_expected} relaciones aplicadas")
            if total_expected > 0:
                percentage = (total_applied / total_expected) * 100
                logger.info(f"[M2M IMPORT] 📊 Porcentaje de éxito: {percentage:.2f}%")
            
        except Exception as e:
            logger.error(f"[M2M IMPORT] Error procesando imports para {model}: {e}")
            import traceback
            logger.debug(f"[M2M IMPORT] Traceback: {traceback.format_exc()}")
        
        logger.info("=" * 80)
        logger.info(f"✓ RELACIONES MANY2MANY DESDE IMPORTS PARA {model} COMPLETADAS")
        logger.info("=" * 80)
    
    def _migrate_batches(self, model: str, records_to_migrate: List[Dict], 
                        v13_ids: List[int], phase: str = "") -> Dict[str, Any]:
        """
        Migra registros en batches.
        
        Args:
            model: Nombre del modelo
            records_to_migrate: Lista de registros a migrar
            v13_ids: Lista de IDs v13 correspondientes
            phase: Fase de migración (para logging)
        
        Returns:
            Diccionario con estadísticas
        """
        # Tamaño de batch específico por modelo
        # Tamaño de batch estándar
        batch_size = self.batch_size
        
        total_batches = (len(records_to_migrate) + batch_size - 1) // batch_size
        stats = {
            'created': 0,
            'skipped': 0,
            'errors': 0,
            'total': len(records_to_migrate)
        }
        
        phase_text = f" ({phase})" if phase else ""
        logger.info(f"[MIGRACIÓN{phase_text}] Total de batches: {total_batches} (tamaño: {batch_size} registros por batch)")
        
        for i in range(0, len(records_to_migrate), batch_size):
            batch_num = (i // batch_size) + 1
            batch_records = records_to_migrate[i:i + batch_size]
            batch_v13_ids = v13_ids[i:i + batch_size]
            batch_id = f"{model}_{batch_num}_{total_batches}"
            batch_uom_name_changes = []  # Inicializar para este método
            
            logger.info(f"[MIGRACIÓN{phase_text}] Batch {batch_num}/{total_batches} en proceso ({len(batch_records)} registros)...")
            
            if self.test_mode:
                logger.info(f"[MODO TEST] Simulando migración de {len(batch_records)} registros (NO se crearán en v18)")
                # En modo test, simular creación
                stats['created'] += len(batch_records)
                logger.info(f"[MODO TEST] Batch {batch_num}/{total_batches} simulado - "
                          f"Simulados: {len(batch_records)}, "
                          f"Omitidos: 0, "
                          f"Errores: 0")
            else:
                try:
                    result = self.v18_conn.migrate_batch(
                        model,
                        batch_records,
                        batch_v13_ids,
                        batch_id
                    )
                    
                    batch_stats = result.get('stats', {})
                    stats['created'] += batch_stats.get('created', 0)
                    stats['skipped'] += batch_stats.get('skipped', 0)
                    stats['errors'] += batch_stats.get('errors', 0)
                    
                    logger.info(f"[MIGRACIÓN{phase_text}] Batch {batch_num}/{total_batches} completado - "
                              f"Creados: {batch_stats.get('created', 0)}, "
                              f"Omitidos: {batch_stats.get('skipped', 0)}, "
                              f"Errores: {batch_stats.get('errors', 0)}")
                    
                    # Registrar cambios de nombre de uom en migration.tracking
                    if batch_uom_name_changes:
                        self._register_uom_name_changes(batch_uom_name_changes, batch_id)
                    
                except Exception as e:
                    logger.error(f"[ERROR] Error en batch {batch_num}/{total_batches}: {e}")
                    stats['errors'] += len(batch_records)
        
        logger.info(f"[MIGRACIÓN{phase_text}] ✓ Todos los batches completados")
        return stats
    
    def load_models_from_file(self, filepath: str = 'models_to_migrate.txt') -> List[Dict[str, Any]]:
        """
        Carga la lista de modelos a migrar desde un archivo de texto.
        
        Formato del archivo:
        - Cada línea contiene un modelo
        - Formato: modelo:allow_many2one (ej: res.partner:True)
        - Si no se especifica allow_many2one, por defecto es False
        - Las líneas que empiezan con # son comentarios y se ignoran
        - Las líneas vacías se ignoran
        
        Args:
            filepath: Ruta al archivo de texto con los modelos
        
        Returns:
            Lista de diccionarios con configuración de modelos
        """
        models_to_migrate = []
        
        if not os.path.exists(filepath):
            logger.warning(f"⚠ Archivo {filepath} no encontrado")
            return models_to_migrate
        
        logger.info(f"Leyendo modelos desde {filepath}...")
        
        with open(filepath, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                
                # Ignorar líneas vacías y comentarios
                if not line or line.startswith('#'):
                    continue
                
                # Parsear línea: modelo:allow_many2one o solo modelo
                if ':' in line:
                    parts = line.split(':', 1)
                    model = parts[0].strip()
                    allow_many2one_str = parts[1].strip().lower()
                    
                    # Convertir string a boolean
                    allow_many2one = allow_many2one_str in ('true', '1', 'yes', 'si', 'sí')
                else:
                    model = line.strip()
                    allow_many2one = False
                
                if not model:
                    logger.warning(f"⚠ Línea {line_num} vacía o inválida, saltando...")
                    continue
                
                models_to_migrate.append({
                    'model': model,
                    'allow_many2one': allow_many2one,
                    'json_file': None
                })
        
        logger.info(f"✓ Cargados {len(models_to_migrate)} modelos desde {filepath}")
        return models_to_migrate


def main():
    """
    Función principal.
    
    Lee los modelos a migrar desde el archivo models_to_migrate.txt
    o desde la variable de entorno MODELS_FILE.
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info("SCRIPT DE MIGRACIÓN ODOO v13 -> v18")
    logger.info("=" * 80)
    logger.info("[INICIO] Archivos de log:")
    logger.info(f"  📄 Log completo: {log_file}")
    logger.info(f"  🐛 Log debug: {debug_file}")
    logger.info(f"  ❌ Log errores: {error_file}")
    
    # Verificar modo test
    test_mode = os.getenv('TEST_MODE', 'False').lower() in ('true', '1', 'yes', 'si', 'sí')
    if test_mode:
        logger.info("⚠⚠⚠ MODO TEST ACTIVADO ⚠⚠⚠")
        logger.info("⚠ NO se crearán registros en la base de datos v18")
        logger.info("⚠ Solo se simulará la migración")
    
    logger.info("=" * 80)
    logger.info("")
    
    script = MigrationScript()
    
    try:
        logger.info("[INICIO] Cargando configuración...")
        script.load_env()
        logger.info("[INICIO] ✓ Configuración cargada")
        
        # Verificar si se especificó un modelo específico para migrar
        # NOTA: Esta variable puede estar definida en el entorno del sistema o en .env
        migrate_models_env = os.getenv('MIGRATE_MODEL', '').strip()
        
        if migrate_models_env:
            # Soportar múltiples modelos separados por comas
            migrate_models = [m.strip() for m in migrate_models_env.split(',') if m.strip()]
            
            if len(migrate_models) == 1:
                logger.info(f"[INICIO] ⚠ Modo de migración única: Solo se migrará '{migrate_models[0]}'")
            else:
                logger.info(f"[INICIO] ⚠ Modo de migración múltiple: Se migrarán {len(migrate_models)} modelos: {', '.join(migrate_models)}")
            
            logger.info(f"[INICIO] (Variable de entorno MIGRATE_MODEL='{migrate_models_env}' detectada)")
            logger.info("[INICIO] Para migrar todos los modelos, desactiva esta variable o elimínala del .env")
            
            # Crear configuración para los modelos especificados
            # Intentar determinar allow_many2one desde el archivo si existe
            models_file = os.getenv('MODELS_FILE', 'models_to_migrate.txt')
            model_configs = {}  # Diccionario para almacenar allow_many2one por modelo
            
            if os.path.exists(models_file):
                try:
                    with open(models_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith('#'):
                                continue
                            if ':' in line:
                                model_name, allow_str = line.split(':', 1)
                                model_name = model_name.strip()
                                if model_name in migrate_models:
                                    model_configs[model_name] = allow_str.strip().lower() in ('true', '1', 'yes', 'si', 'sí')
                            elif line in migrate_models:
                                model_configs[line] = False
                except Exception as e:
                    logger.warning(f"[INICIO] ⚠ No se pudo leer {models_file} para determinar allow_many2one: {e}")
            
            # Crear lista de modelos a migrar
            models_to_migrate = []
            for model_name in migrate_models:
                allow_many2one = model_configs.get(model_name, False)
                models_to_migrate.append({
                    'model': model_name,
                    'allow_many2one': allow_many2one,
                    'json_file': None
                })
                logger.info(f"[INICIO] ✓ Modelo configurado: {model_name} (allow_many2one={allow_many2one})")
        else:
            # Cargar modelos desde archivo
            logger.info("[INICIO] Cargando lista de modelos a migrar...")
            models_file = os.getenv('MODELS_FILE', 'models_to_migrate.txt')
            models_to_migrate = script.load_models_from_file(models_file)
            
            if not models_to_migrate:
                logger.warning("[ERROR] ⚠ No se especificaron modelos para migrar.")
                logger.info(f"[INFO] Edita el archivo {models_file} y agrega los modelos a migrar")
                logger.info("[INFO] Formato: modelo:allow_many2one (ej: res.partner:True)")
                logger.info("[INFO] O usa la variable de entorno MIGRATE_MODEL para migrar un solo modelo")
                return
            
            script.total_models = len(models_to_migrate)
            logger.info(f"[INICIO] ✓ {script.total_models} modelos cargados desde {models_file}")
        
        script.total_models = len(models_to_migrate)
        
        # Ordenar modelos por dependencias (topological sort)
        logger.info("")
        logger.info("[PREPARACIÓN] Analizando dependencias entre modelos...")
        sorted_models = script.sort_models_by_dependencies(models_to_migrate)
        models_list = [m['model'] for m in sorted_models]
        logger.info(f"[PREPARACIÓN] ✓ Orden de migración determinado: {len(sorted_models)} modelos")
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("INICIANDO PROCESO DE MIGRACIÓN")
        logger.info("=" * 80)
        logger.info("")
        
        # Ejecutar migración para cada modelo en orden
        total_stats = {
            'created': 0,
            'skipped': 0,
            'errors': 0,
            'total': 0
        }
        
        for idx, model_config in enumerate(sorted_models):
            script.current_model_index = idx
            model = model_config.get('model')
            allow_many2one = model_config.get('allow_many2one', False)
            json_file = model_config.get('json_file', None)
            
            if not model:
                logger.error("[ERROR] ⚠ Modelo no especificado, saltando...")
                continue
            
            try:
                stats = script.migrate_model(model, json_file, allow_many2one, models_list)
                
                if 'error' not in stats:
                    total_stats['created'] += stats.get('created', 0)
                    total_stats['skipped'] += stats.get('skipped', 0)
                    total_stats['errors'] += stats.get('errors', 0)
                    total_stats['total'] += stats.get('total', 0)
                    
                    # Esperar un momento para que se registre en migration.tracking
                    import time
                    time.sleep(0.5)
                else:
                    logger.error(f"[ERROR] Error en {model}: {stats.get('error')}")
            except Exception as e:
                logger.error(f"[ERROR] ✗ Error migrando {model}: {e}")
                import traceback
                traceback.print_exc()
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("APLICANDO RELACIONES MANY2MANY")
        logger.info("=" * 80)
        logger.info("[M2M FINAL] Todas las tablas están migradas, aplicando relaciones many2many...")
        logger.info("[M2M FINAL] Esto asegura que ambos modelos relacionados existan en la DB antes de aplicar relaciones")
        
        # Aplicar relaciones many2many después de que todos los modelos estén migrados
        # Esto asegura que ambos modelos relacionados existan en la DB antes de aplicar relaciones
        for model_config in sorted_models:
            model = model_config.get('model')
            if not model:
                continue
            
            logger.info("")
            logger.info(f"[M2M FINAL] Aplicando relaciones many2many para {model}...")
            
            # Aplicar relaciones desde tablas intermedias
            script._migrate_many2many_relations(model, models_list)
            
            # Aplicar relaciones desde imports (campos que vienen como arrays simples)
            script._apply_m2m_from_imports(model, models_list)
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("MIGRACIÓN COMPLETADA")
        logger.info("=" * 80)
        logger.info("RESUMEN TOTAL:")
        logger.info(f"  ✓ Creados: {total_stats['created']}")
        logger.info(f"  ⊘ Omitidos (duplicados): {total_stats['skipped']}")
        logger.info(f"  ✗ Errores: {total_stats['errors']}")
        logger.info(f"  📊 Total procesados: {total_stats['total']}")
        logger.info("=" * 80)
        logger.info("[INICIO] Archivos de log generados:")
        logger.info(f"  📄 Log completo: {log_file}")
        logger.info(f"  🐛 Log debug: {debug_file}")
        logger.info(f"  ❌ Log errores: {error_file}")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error("=" * 80)
        logger.error("[ERROR FATAL] Error en migración:")
        logger.error(str(e))
        logger.error("=" * 80)
        import traceback
        # Registrar traceback completo en el log de errores
        logger.error(f"[ERROR FATAL] Traceback completo:\n{traceback.format_exc()}")
        traceback.print_exc()
        raise


if __name__ == '__main__':
    main()

