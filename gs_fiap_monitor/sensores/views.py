from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db import transaction
import json
from datetime import datetime, timedelta
from collections import defaultdict
import requests
from django.contrib import messages
from django.urls import reverse, NoReverseMatch
import pytz

import plotly.express as px
import pandas as pd

from .models import Dispositivo, TipoSensor, LeituraSensor
from .forms import DispositivoLocalizacaoForm

# Função auxiliar para tentar parsear timestamps
def parse_timestamp(timestamp_str):
    if not timestamp_str:
        return timezone.now()
    try:
        # Tenta o formato ISO 8601 com Z (UTC)
        return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
    except ValueError:
        try:
            # Exemplo: datetime.strptime(timestamp_str, '%Y-%m-%dT%H:%M:%S.%f')
            print(f"Alerta: Não foi possível parsear o timestamp '{timestamp_str}'. Usando hora atual.")
            return timezone.now()
        except ValueError:
            print(f"Erro Crítico: Formato de timestamp '{timestamp_str}' completamente desconhecido. Usando hora atual.")
            return timezone.now()

@csrf_exempt
def fiware_notification_receiver(request):
    if request.method == 'POST':
        try:
            payload = json.loads(request.body.decode('utf-8'))
            print("Payload recebido do Fiware:")
            print(json.dumps(payload, indent=4))

            entities_data = payload.get('data')
            if not isinstance(entities_data, list):
                print("Erro: Formato de payload inesperado. Esperava uma lista de entidades em 'data'.")
                return HttpResponse("Erro: Payload malformado, 'data' não é uma lista.", status=400)

            with transaction.atomic():
                for entity in entities_data:
                    device_fiware_id = entity.get('id')
                    entity_type = entity.get('type') # Pode ser útil para filtrar ou nomear dispositivos

                    if not device_fiware_id:
                        print(f"Alerta: Entidade recebida sem 'id'. Ignorando: {entity}")
                        continue

                    # Encontra ou cria o dispositivo
                    dispositivo, created = Dispositivo.objects.get_or_create(
                        id_dispositivo_fiware=device_fiware_id,
                        defaults={ 'nome_dispositivo': device_fiware_id, 'descricao': f"Dispositivo {entity_type or 'Desconhecido'}"}
                    )
                    if created:
                        print(f"Dispositivo '{dispositivo.nome_dispositivo}' criado.")

                    # Extrai o timestamp da leitura da entidade.
                    timestamp_leitura_str = None
                    if 'timestamp' in entity and isinstance(entity['timestamp'], dict) and 'value' in entity['timestamp']:
                        timestamp_leitura_str = entity['timestamp']['value']
                    elif 'TimeInstant' in entity and isinstance(entity['TimeInstant'], dict) and 'value' in entity['TimeInstant']:
                        timestamp_leitura_str = entity['TimeInstant']['value']
                    elif 'TimeInstant' in entity and isinstance(entity['TimeInstant'], str):
                        timestamp_leitura_str = entity['TimeInstant']
                    elif 'timestamp' in entity and isinstance(entity['timestamp'], str):
                        timestamp_leitura_str = entity['timestamp']
                    else:
                        # Tentar encontrar em metadados de algum atributo (ex: dateObserved)
                        for attr_name, attr_data in entity.items():
                            if isinstance(attr_data, dict) and 'metadata' in attr_data:
                                if 'TimeInstant' in attr_data['metadata'] and 'value' in attr_data['metadata']['TimeInstant']:
                                    timestamp_leitura_str = attr_data['metadata']['TimeInstant']['value']
                                    break
                                if 'timestamp' in attr_data['metadata'] and 'value' in attr_data['metadata']['timestamp']:
                                    timestamp_leitura_str = attr_data['metadata']['timestamp']['value']
                                    break
                    
                    if timestamp_leitura_str:
                        timestamp_leitura = parse_timestamp(timestamp_leitura_str)
                    else:
                        timestamp_leitura = timezone.now()

                    # Processa cada atributo da entidade como uma possível leitura de sensor
                    for attr_name, attr_data in entity.items():
                        # Ignora atributos padrão do NGSI que não são leituras de sensor
                        if attr_name in ['id', 'type', 'TimeInstant', 'timestamp'] or not isinstance(attr_data, dict):
                            continue
                        
                        # Consideramos um atributo como leitura se tiver 'value' e for numérico
                        attr_value = attr_data.get('value')
                        attr_type_ngsi = attr_data.get('type') # Ex: 'Number', 'Text'

                        if attr_value is not None and isinstance(attr_value, (int, float)):
                            # Encontra ou cria o TipoSensor
                            # Se a unidade não for fornecida, você pode querer adicionar lógica para inferi-la ou deixar como padrão
                            unidade = attr_data.get('metadata', {}).get('unitCode', {}).get('value') or \
                                      attr_data.get('metadata', {}).get('unit', {}).get('value') or \
                                      'Desconhecida'
                            
                            tipo_sensor, created_type = TipoSensor.objects.get_or_create(
                                nome=attr_name, # Usando o nome do atributo Fiware como nome do sensor
                                defaults={'unidade_medida': unidade, 'descricao': f"Sensor para {attr_name}"}
                            )
                            if created_type or (tipo_sensor.unidade_medida == 'Desconhecida' and unidade != 'Desconhecida'):
                                tipo_sensor.unidade_medida = unidade
                                tipo_sensor.save()

                            # Cria e salva a LeituraSensor
                            LeituraSensor.objects.create(
                                dispositivo=dispositivo,
                                tipo_sensor=tipo_sensor,
                                valor=attr_value,
                                timestamp_leitura=timestamp_leitura,
                                # timestamp_recebimento é default=timezone.now()
                            )
                        elif attr_value is not None:
                            pass # Valor não numérico já logado pela função de print que será removida ou já foi

            return HttpResponse("Notificação processada com sucesso.", status=200)
        except json.JSONDecodeError:
            return HttpResponse("Erro: JSON inválido.", status=400)
        except Exception as e:
            print(f"Erro crítico ao processar notificação: {e}")
            # Em produção, logar o traceback completo aqui seria importante
            return HttpResponse(f"Erro interno ao processar notificação: {str(e)}", status=500)
    else:
        return HttpResponse("Método não permitido. Use POST.", status=405)

def listar_dispositivos(request):
    dispositivos_list = Dispositivo.objects.all().order_by('nome_dispositivo')
    
    nome_sensor_nivel_agua = 'waterLevel'

    SENSOR_NOME_TRADUZIDO = {
        'humidity': 'Umidade',
        'temperature': 'Temperatura',
        'waterLevel': 'Nível de água',
    }

    for dispositivo in dispositivos_list:
        dispositivo.ultimas_leituras_dict = {}
        tipos_sensores_usados_ids = LeituraSensor.objects.filter(dispositivo=dispositivo).values_list('tipo_sensor_id', flat=True).distinct()
        tipos_sensores_usados = TipoSensor.objects.filter(id__in=tipos_sensores_usados_ids)

        ultima_leitura_nivel_agua = None
        timestamp_mais_recente_geral = None # Para status operacional
        dispositivo.timestamp_do_ultimo_registro = None # Inicializa o novo atributo

        if not tipos_sensores_usados.exists():
            pass # Nenhuma ação específica se não houver tipos de sensores associados

        for tipo_sensor in tipos_sensores_usados:
            ultima_leitura = LeituraSensor.objects.filter(dispositivo=dispositivo, tipo_sensor=tipo_sensor).order_by('-timestamp_leitura').first()
            if ultima_leitura:
                nome_traduzido = SENSOR_NOME_TRADUZIDO.get(tipo_sensor.nome, tipo_sensor.nome)
                dispositivo.ultimas_leituras_dict[nome_traduzido] = {
                    'valor': ultima_leitura.valor,
                    'unidade_medida': tipo_sensor.unidade_medida,
                    'timestamp_leitura': ultima_leitura.timestamp_leitura,
                    'object': ultima_leitura # Importante para pegar o timestamp original
                }
                if tipo_sensor.nome == nome_sensor_nivel_agua:
                    ultima_leitura_nivel_agua = ultima_leitura.valor
                
                # Atualiza o timestamp mais recente geral para este dispositivo
                if timestamp_mais_recente_geral is None or ultima_leitura.timestamp_leitura > timestamp_mais_recente_geral:
                    timestamp_mais_recente_geral = ultima_leitura.timestamp_leitura
            else:
                pass # Nenhuma leitura encontrada para este tipo de sensor no dispositivo
        
        dispositivo.timestamp_do_ultimo_registro = timestamp_mais_recente_geral # Atribui o valor calculado

        # Determinar status do dispositivo (baseado em waterLevel)
        dispositivo.status = 'normal' # Default
        if ultima_leitura_nivel_agua is not None:
            try:
                valor_nivel = float(ultima_leitura_nivel_agua)
                if valor_nivel > 80: # Limite para crítico
                    dispositivo.status = 'critical'
                elif valor_nivel > 50: # Limite para moderado
                    dispositivo.status = 'moderate'
            except ValueError:
                pass # Valor não numérico já tratado ou logado anteriormente

        # Determinar status operacional (Online/Offline)
        dispositivo.status_operacional = 'Offline' # Default
        if timestamp_mais_recente_geral:
            limite_inatividade = timedelta(hours=2)
            agora_utc = timezone.now()
            if (agora_utc - timestamp_mais_recente_geral) < limite_inatividade:
                dispositivo.status_operacional = 'Online'
            else:
                pass # Offline por inatividade, log já existia ou pode ser adicionado se necessário para monitoramento
        else:
            pass # Offline por falta de leituras, log já existia ou pode ser adicionado

    context = {
        'dispositivos': dispositivos_list,
        'pagina_atual': 'listar_dispositivos'
    }
    return render(request, 'sensores/listar_dispositivos.html', context)

# View para a home page simplificada
def home_page(request):
    context = {
        'pagina_atual': 'home',
        # Outros dados que a home page possa precisar no futuro (ex: notícias, estatísticas gerais)
    }
    return render(request, 'sensores/home.html', context)

def hub_sensores_view(request):
    context = {
        'pagina_atual': 'hub_sensores', # Para destacar no menu, se aplicável
    }
    return render(request, 'sensores/hub_sensores.html', context)

# View para a nova página do mapa interativo
def mapa_interativo(request): # Assumindo que o nome correto da função seja este, baseado no seu urls.py
    dispositivos_ativos = Dispositivo.objects.filter(ativo=True).order_by('nome_dispositivo')
    
    dispositivos_map_data = []
    nome_sensor_nivel_agua = 'waterLevel' 
    SENSOR_NOME_TRADUZIDO_MAPA = {
        'humidity': 'Umidade',
        'temperature': 'Temperatura',
        'waterLevel': 'Nível de Água',
    }

    brasilia_tz = pytz.timezone('America/Sao_Paulo')

    for disp in dispositivos_ativos:
        ultimas_leituras_detalhadas = [] 
        tipos_sensores_usados_ids = LeituraSensor.objects.filter(dispositivo=disp).values_list('tipo_sensor_id', flat=True).distinct()
        tipos_sensores_usados = TipoSensor.objects.filter(id__in=tipos_sensores_usados_ids)
        
        ultima_leitura_nivel_agua_valor = None
        timestamp_mais_recente_geral = None

        for ts in tipos_sensores_usados:
            ultima_leitura = LeituraSensor.objects.filter(dispositivo=disp, tipo_sensor=ts).order_by('-timestamp_leitura').first()
            if ultima_leitura:
                nome_traduzido = SENSOR_NOME_TRADUZIDO_MAPA.get(ts.nome, ts.nome)
                
                # Guardar timestamp original para ordenação ou formatação mais precisa no JS se necessário
                timestamp_dt = ultima_leitura.timestamp_leitura 

                ultimas_leituras_detalhadas.append({
                    'nome_sensor': nome_traduzido, # Nome traduzido do sensor
                    'valor': ultima_leitura.valor,
                    'unidade_medida': ts.unidade_medida,
                    'timestamp_dt': timestamp_dt,
                    'nome_original': ts.nome # Adicionado para ajudar a selecionar ícones no JS
                })

                if ts.nome == nome_sensor_nivel_agua:
                    ultima_leitura_nivel_agua_valor = ultima_leitura.valor
                
                if timestamp_mais_recente_geral is None or ultima_leitura.timestamp_leitura > timestamp_mais_recente_geral:
                    timestamp_mais_recente_geral = ultima_leitura.timestamp_leitura
        
        status_nivel_agua_code = 'normal' # Para a cor do marcador e lógica interna
        status_nivel_agua_texto = 'Normal' # Para exibição no popup
        if ultima_leitura_nivel_agua_valor is not None:
            try:
                valor_nivel = float(ultima_leitura_nivel_agua_valor)
                if valor_nivel > 80:
                    status_nivel_agua_code = 'critical'
                    status_nivel_agua_texto = 'Crítico'
                elif valor_nivel > 50:
                    status_nivel_agua_code = 'moderate'
                    status_nivel_agua_texto = 'Moderado'
            except ValueError:
                status_nivel_agua_texto = 'Indefinido' 

        status_operacional_disp = 'Offline'
        if timestamp_mais_recente_geral:
            limite_inatividade = timedelta(hours=2) 
            agora_utc = timezone.now()
            if (agora_utc - timestamp_mais_recente_geral) < limite_inatividade:
                status_operacional_disp = 'Online'

        status_admin_texto = "Ativo" if disp.ativo else "Inativo"

        try:
            url_detalhes = reverse('sensores:detalhes_dispositivo', args=[disp.id_dispositivo_fiware])
        except NoReverseMatch:
            url_detalhes = "#"
        
        try:
            url_editar_localizacao = reverse('sensores:editar_localizacao_dispositivo', args=[disp.id_dispositivo_fiware])
        except NoReverseMatch:
            url_editar_localizacao = "#"

        dispositivos_map_data.append({
            'id_dispositivo_fiware': disp.id_dispositivo_fiware,
            'nome': disp.nome_dispositivo,
            'latitude': disp.localizacao_latitude,
            'longitude': disp.localizacao_longitude,
            'descricao': disp.descricao or "Sem descrição.",
            'ultimas_leituras_detalhadas': ultimas_leituras_detalhadas, 
            'status_marcador_code': status_nivel_agua_code, # Para a cor do marcador no JS
            'status_nivel_agua_texto': status_nivel_agua_texto, # Para exibir no popup
            'status_operacional': status_operacional_disp, 
            'status_admin_texto': status_admin_texto, 
            'url_detalhes': url_detalhes,
            'url_editar_localizacao': url_editar_localizacao 
        })

    context = {
        'pagina_atual': 'mapa',
        'dispositivos_map_data': dispositivos_map_data
    }
    return render(request, 'sensores/mapa_interativo.html', context)

def detalhes_dispositivo(request, id_dispositivo_fiware):
    dispositivo = get_object_or_404(Dispositivo, id_dispositivo_fiware=id_dispositivo_fiware)
    leituras = LeituraSensor.objects.filter(dispositivo=dispositivo).order_by('tipo_sensor__nome', 'timestamp_leitura')

    SENSOR_NOME_TRADUZIDO_DETALHES = {
        'humidity': 'Umidade',
        'temperature': 'Temperatura',
        'waterLevel': 'Nível de água',
    }

    # Lógica para determinar o status do dispositivo (baseado em waterLevel do DB local)
    nome_sensor_nivel_agua = 'waterLevel' 
    ultima_leitura_nivel_agua_obj = LeituraSensor.objects.filter(
        dispositivo=dispositivo, 
        tipo_sensor__nome=nome_sensor_nivel_agua
    ).order_by('-timestamp_leitura').first()

    dispositivo.status_calculado = 'normal' 
    if ultima_leitura_nivel_agua_obj and isinstance(ultima_leitura_nivel_agua_obj.valor, (int, float)):
        valor_nivel = float(ultima_leitura_nivel_agua_obj.valor)
        if valor_nivel > 80:
            dispositivo.status_calculado = 'critical'
        elif valor_nivel > 50:
            dispositivo.status_calculado = 'moderate'
    elif ultima_leitura_nivel_agua_obj: 
        dispositivo.status_calculado = 'unknown'

    # Determinar status operacional (Online/Offline) para a página de detalhes
    dispositivo.status_operacional = 'Offline' # Default
    timestamp_mais_recente_bd = LeituraSensor.objects.filter(dispositivo=dispositivo).order_by('-timestamp_leitura').values_list('timestamp_leitura', flat=True).first()

    if timestamp_mais_recente_bd:
        limite_inatividade = timedelta(hours=2) # Limite de 2 horas (consistente com listar_dispositivos)
        agora_utc = timezone.now()
        if (agora_utc - timestamp_mais_recente_bd) < limite_inatividade:
            dispositivo.status_operacional = 'Online'
        else:
            pass # Offline por inatividade
    else:
        pass # Offline por falta de leituras

    # Buscar dados ao vivo do Fiware
    dados_fiware_live = {}
    timestamp_leitura_fiware_live = timezone.now() # Default para o momento da busca
    timestamp_fiware_em_brasilia = None 
    dados_fiware_formatados = [] 

    try:
        fiware_url = f"http://20.55.19.44:1026/v2/entities/{id_dispositivo_fiware}" 
        headers = {
            'Accept': 'application/json',
            'fiware-service': 'smart',
            'fiware-servicepath': '/'
        }
        response = requests.get(fiware_url, headers=headers, timeout=5) 
        response.raise_for_status() # Levanta exceção para respostas de erro HTTP (4xx ou 5xx)
        dados_fiware_live = response.json()
        
        # Tentar extrair e parsear o timestamp principal da entidade
        timestamp_leitura_fiware_str = None
        if 'TimeInstant' in dados_fiware_live and isinstance(dados_fiware_live['TimeInstant'], dict) and 'value' in dados_fiware_live['TimeInstant']:
            timestamp_leitura_fiware_str = dados_fiware_live['TimeInstant']['value']
        elif 'timestamp' in dados_fiware_live and isinstance(dados_fiware_live['timestamp'], dict) and 'value' in dados_fiware_live['timestamp']:
            timestamp_leitura_fiware_str = dados_fiware_live['timestamp']['value']

        if timestamp_leitura_fiware_str:
            parsed_ts = parse_timestamp(timestamp_leitura_fiware_str)
            if parsed_ts: # parse_timestamp pode retornar None ou levantar exceção em caso de falha total (improvável com o fallback dela)
                timestamp_leitura_fiware_live = parsed_ts
                # Guardar o timestamp parseado para possível uso no template, se necessário
                if 'TimeInstant' in dados_fiware_live:
                    dados_fiware_live['TimeInstantParsed'] = parsed_ts
                elif 'timestamp' in dados_fiware_live:
                    dados_fiware_live['timestampParsed'] = parsed_ts
                
                # Converter para Brasília
                brasilia_tz = pytz.timezone('America/Sao_Paulo')
                if timezone.is_aware(timestamp_leitura_fiware_live):
                    timestamp_fiware_em_brasilia = timestamp_leitura_fiware_live.astimezone(brasilia_tz)
                else:
                    # Se parse_timestamp retornar um datetime naive (embora tente retornar aware com +00:00),
                    # assumimos UTC e tornamos aware antes de converter.
                    timestamp_fiware_em_brasilia = pytz.utc.localize(timestamp_leitura_fiware_live).astimezone(brasilia_tz)
        else:
            # timestamp_leitura_fiware_live já tem timezone.now() como default no início da função
            pass # Nenhum timestamp principal encontrado

        if not dados_fiware_live.get('erro_fiware'):
            for attr_name, attr_data in dados_fiware_live.items():
                if attr_name in ['id', 'type', 'TimeInstant', 'timestamp', 'TimeInstantParsed', 'timestampParsed', 'location', 'erro_fiware'] or \
                   not isinstance(attr_data, dict) or 'value' not in attr_data:
                    continue

                valor = attr_data.get('value')
                unidade = None
                timestamp_attr_dt = None
                timestamp_attr_iso = None

                if isinstance(attr_data.get('metadata'), dict):
                    meta = attr_data['metadata']
                    if isinstance(meta.get('unitCode'), dict) and 'value' in meta['unitCode']:
                        unidade = meta['unitCode']['value']
                    elif isinstance(meta.get('unit'), dict) and 'value' in meta['unit']:
                        unidade = meta['unit']['value']
                    
                    if isinstance(meta.get('TimeInstant'), dict) and 'value' in meta['TimeInstant']:
                        timestamp_attr_str = meta['TimeInstant']['value']
                        timestamp_attr_dt = parse_timestamp(timestamp_attr_str)
                        if timestamp_attr_dt:
                            timestamp_attr_iso = timestamp_attr_dt.isoformat()
                            # Atualiza o timestamp mais recente geral se este atributo for mais novo
                            if timestamp_fiware_em_brasilia is None or timestamp_attr_dt > timestamp_fiware_em_brasilia:
                                timestamp_fiware_em_brasilia = timestamp_attr_dt
            
                if unidade is None: # Fallback de unidade
                    if 'temperature' in attr_name.lower(): unidade = '°C'
                    elif 'humidity' in attr_name.lower(): unidade = '%'
                    elif 'waterlevel' in attr_name.lower(): unidade = '%'
                
                nome_exibicao = SENSOR_NOME_TRADUZIDO_DETALHES.get(attr_name, attr_name.replace('_', ' ').capitalize())
                
                dados_fiware_formatados.append({
                    'nome': nome_exibicao,
                    'valor': valor,
                    'unidade': unidade,
                    'timestamp_dt_iso': timestamp_attr_iso if timestamp_attr_iso else timestamp_fiware_em_brasilia, # Usa timestamp do atributo ou geral
                    'nome_original': attr_name 
                })

        if not dados_fiware_live.get('erro_fiware'): # Só processa se não houve erro na busca
            with transaction.atomic():
                for attr_name, attr_data in dados_fiware_live.items():
                    # Ignora atributos padrão do NGSI que não são leituras de sensor diretas
                    if attr_name in ['id', 'type', 'TimeInstant', 'timestamp', 'TimeInstantParsed', 'timestampParsed', 'location'] or \
                       not isinstance(attr_data, dict) or 'value' not in attr_data:
                        continue
                    
                    attr_value_raw = attr_data.get('value')
                    
                    # Tenta converter o valor para numérico (float). Se falhar, ignora este atributo.
                    # Baseado no seu exemplo, mesmo com "type": "Text", o valor pode ser numérico.
                    current_value = None
                    if isinstance(attr_value_raw, (int, float)):
                        current_value = float(attr_value_raw)
                    elif isinstance(attr_value_raw, str):
                        try:
                            current_value = float(attr_value_raw)
                        except ValueError:
                            continue
                    else:
                        # Ignora outros tipos de valor (booleanos, listas, objetos complexos não tratados aqui)
                        continue

                    # Checar se current_value foi definido (ou seja, é um número)
                    if current_value is None:
                        continue

                    # Determinar a unidade, aplicando fallback se necessário, para salvar no BD
                    unidade_para_db = None
                    if isinstance(attr_data.get('metadata'), dict):
                        meta_db = attr_data['metadata']
                        if isinstance(meta_db.get('unitCode'), dict) and 'value' in meta_db['unitCode']:
                            unidade_para_db = meta_db['unitCode']['value']
                        elif isinstance(meta_db.get('unit'), dict) and 'value' in meta_db['unit']:
                            unidade_para_db = meta_db['unit']['value']

                    # Aplicar fallback se a unidade não veio do Fiware, é None ou explicitamente "Desconhecida"
                    if unidade_para_db is None or unidade_para_db.strip() == '' or unidade_para_db.lower() == 'desconhecida':
                        if 'temperature' in attr_name.lower():
                            unidade_para_db = '°C'
                        elif 'humidity' in attr_name.lower():
                            unidade_para_db = '%'
                        elif 'waterlevel' in attr_name.lower() or 'waterLevel' in attr_name: # Adicionado waterLevel para consistência
                            unidade_para_db = '%'
                        else:
                            unidade_para_db = 'Desconhecida' # Mantém desconhecida se não for um tipo esperado
                    
                    # Encontra ou cria o TipoSensor
                    tipo_sensor_obj, created_type_sensor = TipoSensor.objects.get_or_create(
                        nome=attr_name, # Usando o nome do atributo Fiware como nome do sensor
                        defaults={'unidade_medida': unidade_para_db, 'descricao': f"Sensor para {attr_name}"}
                    )

                    # Atualiza a unidade se:
                    # 1. O tipo de sensor foi recém-criado E a unidade_para_db não é 'Desconhecida'.
                    # 2. A unidade armazenada era 'Desconhecida' E a nova unidade_para_db não é 'Desconhecida'.
                    # 3. A unidade armazenada é diferente da nova unidade_para_db E a nova unidade_para_db não é 'Desconhecida'.
                    if (created_type_sensor and unidade_para_db != 'Desconhecida') or \
                       (tipo_sensor_obj.unidade_medida == 'Desconhecida' and unidade_para_db != 'Desconhecida') or \
                       (tipo_sensor_obj.unidade_medida != unidade_para_db and unidade_para_db != 'Desconhecida'):
                        tipo_sensor_obj.unidade_medida = unidade_para_db
                        tipo_sensor_obj.save()
                    
                    # Determina o timestamp da leitura específica do atributo, ou usa o global da entidade
                    timestamp_leitura_attr_str = None
                    if isinstance(attr_data.get('metadata'), dict) and \
                       isinstance(attr_data['metadata'].get('TimeInstant'), dict) and \
                       'value' in attr_data['metadata']['TimeInstant']:
                        timestamp_leitura_attr_str = attr_data['metadata']['TimeInstant']['value']
                    
                    timestamp_leitura_para_db = parse_timestamp(timestamp_leitura_attr_str) if timestamp_leitura_attr_str else timestamp_fiware_live

                    # Cria ou atualiza a LeituraSensor
                    # Para evitar duplicatas baseadas em "mesmo sensor, mesmo timestamp", usamos update_or_create
                    # Isso pressupõe que (dispositivo, tipo_sensor, timestamp_leitura) é uma tupla razoavelmente única.
                    # Se múltiplos updates para o mesmo micro-segundo puderem ocorrer e forem significativos,
                    # esta lógica pode precisar de ajuste ou pode-se simplesmente usar create() e ter múltiplos registros.
                    # A notificação do Fiware já usa create(). Para consistência e simplicidade, vamos manter create() aqui também,
                    # já que o polling é menos frequente que notificações.
                    LeituraSensor.objects.create(
                        dispositivo=dispositivo,
                        tipo_sensor=tipo_sensor_obj,
                        valor=current_value,
                        timestamp_leitura=timestamp_leitura_para_db,
                    )

    except requests.exceptions.RequestException as e:
        dados_fiware_live['erro_fiware'] = f"Erro de comunicação com o Fiware: {str(e)}"
    except json.JSONDecodeError:
        dados_fiware_live['erro_fiware'] = "Erro ao decodificar a resposta JSON do Fiware."
    except Exception as e:
        dados_fiware_live['erro_fiware'] = f"Um erro inesperado ocorreu: {str(e)}"

    # Prepara gráficos
    graficos_html = {}
    leituras_do_dispositivo_para_graficos = LeituraSensor.objects.filter(dispositivo=dispositivo)
    tipos_sensores_ids_para_graficos = leituras_do_dispositivo_para_graficos.values_list('tipo_sensor_id', flat=True).distinct()
    tipos_sensores_disponiveis = TipoSensor.objects.filter(id__in=tipos_sensores_ids_para_graficos)

    if tipos_sensores_disponiveis.exists():
        for tipo_sensor in tipos_sensores_disponiveis:
            leituras_sensor = LeituraSensor.objects.filter(dispositivo=dispositivo, tipo_sensor=tipo_sensor).order_by('timestamp_leitura')
            
            if leituras_sensor.count() > 1: # Precisa de pelo menos 2 pontos para um gráfico de linha
                df = pd.DataFrame(list(leituras_sensor.values('timestamp_leitura', 'valor')))
                
                # Converter timestamp_leitura para o fuso horário de Brasília ANTES de plotar
                brasilia_tz = pytz.timezone('America/Sao_Paulo')
                df['timestamp_leitura'] = pd.to_datetime(df['timestamp_leitura']).dt.tz_convert(brasilia_tz)
                
                fig = px.line(df, x='timestamp_leitura', y='valor', 
                              title=f'Histórico de {SENSOR_NOME_TRADUZIDO_DETALHES.get(tipo_sensor.nome, tipo_sensor.nome)}',
                              labels={'timestamp_leitura': 'Data e Hora (Brasília)', 'valor': f'Valor ({tipo_sensor.unidade_medida})'})
                fig.update_layout(
                    title_x=0.5, 
                    title_font_size=16,
                    xaxis_title_font_size=12,
                    yaxis_title_font_size=12,
                    margin=dict(l=40, r=20, t=40, b=20), # Reduzir margens
                    height=300 # Altura fixa para o gráfico
                )
                graficos_html[SENSOR_NOME_TRADUZIDO_DETALHES.get(tipo_sensor.nome, tipo_sensor.nome)] = fig.to_html(full_html=False, include_plotlyjs='cdn')
            elif leituras_sensor.exists():
                graficos_html[SENSOR_NOME_TRADUZIDO_DETALHES.get(tipo_sensor.nome, tipo_sensor.nome)] = f"<p class='text-center text-sm text-gray-600 p-4'>Não há dados suficientes ({leituras_sensor.count()} leitura) para gerar um gráfico de histórico para {SENSOR_NOME_TRADUZIDO_DETALHES.get(tipo_sensor.nome, tipo_sensor.nome)}.</p>"
            else:
                graficos_html[SENSOR_NOME_TRADUZIDO_DETALHES.get(tipo_sensor.nome, tipo_sensor.nome)] = f"<p class='text-center text-sm text-gray-600 p-4'>Nenhuma leitura encontrada para {SENSOR_NOME_TRADUZIDO_DETALHES.get(tipo_sensor.nome, tipo_sensor.nome)}.</p>"
    else:
        # Isso não deveria acontecer se o dispositivo tem leituras, mas é um fallback.
        pass

    context = {
        'dispositivo': dispositivo,
        'leituras': leituras, # Ainda pode ser útil para alguma listagem tabular, se desejado
        'graficos_html': graficos_html,
        'dados_fiware_live': dados_fiware_live, # Mantido para debug ou se o template ainda usar algo dele diretamente
        'dados_fiware_formatados': dados_fiware_formatados, 
        'timestamp_fiware_em_brasilia': timestamp_fiware_em_brasilia, # Passando o timestamp geral formatado
        'pagina_atual': 'detalhes_dispositivo',
    }
    return render(request, 'sensores/detalhes_dispositivo.html', context)

def editar_localizacao_dispositivo(request, id_dispositivo_fiware):
    dispositivo = get_object_or_404(Dispositivo, id_dispositivo_fiware=id_dispositivo_fiware)
    mensagem_sucesso = None
    mensagem_erro_fiware = None

    if request.method == 'POST':
        form = DispositivoLocalizacaoForm(request.POST, instance=dispositivo)
        if form.is_valid():
            try:
                form.save() # Salva no banco de dados Django
                mensagem_sucesso = "Localização atualizada com sucesso no sistema."

                # Atualizar no Fiware
                latitude = form.cleaned_data.get('localizacao_latitude')
                longitude = form.cleaned_data.get('localizacao_longitude')

                if latitude is not None and longitude is not None:
                    fiware_url = f"http://20.55.19.44:1026/v2/entities/{id_dispositivo_fiware}/attrs"
                    headers = {
                        'Content-Type': 'application/json',
                        'fiware-service': 'smart',
                        'fiware-servicepath': '/'
                    }
                    payload = {
                        "location": {
                            "type": "GeoProperty",
                            "value": {
                                "type": "Point",
                                "coordinates": [longitude, latitude] # Longitude, Latitude
                            }
                        }
                    }
                    
                    response_fiware = requests.patch(fiware_url, headers=headers, json=payload, timeout=10)
                    response_fiware.raise_for_status() # Levanta exceção para erros HTTP
                    
                    mensagem_sucesso += " E atualizada no Fiware."
                    if response_fiware.content: # Algumas respostas PATCH bem-sucedidas podem não ter conteúdo
                        pass # Print do content removido

                else:
                    # Se lat/lon foram apagados, a localização no Fiware não é atualizada aqui.
                    # Remover o atributo 'location' do Fiware exigiria uma lógica mais complexa (ex: PUT ou API específica).
                    mensagem_sucesso += " (Localização no Fiware não atualizada pois os campos estão vazios)."

            except requests.exceptions.RequestException as e:
                pass # Erro já logado ou tratado
            except Exception as e:
                # Tratar outros erros gerais se necessário
                pass # Deixa a mensagem de sucesso parcial, erro será mostrado pelo mensagem_erro_fiware
        # Se o formulário não for válido, os erros serão exibidos pelo template
    else:
        form = DispositivoLocalizacaoForm(instance=dispositivo)

    context = {
        'form': form,
        'dispositivo': dispositivo,
        'mensagem_sucesso': mensagem_sucesso,
        'mensagem_erro_fiware': mensagem_erro_fiware,
        'pagina_atual': 'editar_localizacao'
    }
    return render(request, 'sensores/editar_localizacao_dispositivo.html', context)

def detectar_novos_dispositivos_fiware(request):
    if request.method == 'POST':
        max_id_testado = 0
        ultimo_dispositivo_django = Dispositivo.objects.order_by('-id_dispositivo_fiware').first()

        if ultimo_dispositivo_django and ultimo_dispositivo_django.id_dispositivo_fiware.startswith('urn:ngsi-ld:SensorDevice:'):
            try:
                # Extrai a parte numérica do ID, ex: "001" de "urn:ngsi-ld:SensorDevice:001"
                id_numerico_str = ultimo_dispositivo_django.id_dispositivo_fiware.split(':')[-1]
                max_id_testado = int(id_numerico_str)
            except (ValueError, IndexError):
                max_id_testado = 0
        
        id_inicial_check = max_id_testado + 1
        dispositivos_encontrados_fiware = 0
        dispositivos_adicionados_django = 0
        falhas_consecutivas = 0
        max_falhas_para_parar = 10  # Testa mais X IDs após a primeira falha

        headers = {
            'Accept': 'application/json',
            'fiware-service': 'smart',
            'fiware-servicepath': '/'
        }

        for i in range(id_inicial_check, id_inicial_check + 100): # Limite de 100 tentativas para evitar loops longos
            # Formata o ID com 3 dígitos, ex: 1 -> "001", 10 -> "010"
            id_formatado = str(i).zfill(3)
            id_dispositivo_fiware_completo = f"urn:ngsi-ld:SensorDevice:{id_formatado}"
            fiware_url = f"http://20.55.19.44:1026/v2/entities/{id_dispositivo_fiware_completo}" 
            
            print(f"Testando dispositivo: {id_dispositivo_fiware_completo} em {fiware_url}")

            try:
                response = requests.get(fiware_url, headers=headers, timeout=3)
                if response.status_code == 200:
                    dispositivos_encontrados_fiware += 1
                    falhas_consecutivas = 0 # Reseta contador de falhas
                    
                    # Verifica se já existe no Django, se não, cria
                    dispositivo_obj, created = Dispositivo.objects.get_or_create(
                        id_dispositivo_fiware=id_dispositivo_fiware_completo,
                        defaults={
                            'nome_dispositivo': f"ESP32-{id_formatado}", 
                            'descricao': f"Dispositivo ESP32-{id_formatado} ({id_dispositivo_fiware_completo})",
                            'ativo': True # Assume como ativo por padrão
                        }
                    )
                    if created:
                        dispositivos_adicionados_django += 1
                        print(f"Novo dispositivo adicionado ao Django: {id_dispositivo_fiware_completo}")
                    else:
                        print(f"Dispositivo {id_dispositivo_fiware_completo} já existe no Django.")
                
                elif response.status_code == 404:
                    print(f"Dispositivo {id_dispositivo_fiware_completo} não encontrado no Fiware (404).")
                    falhas_consecutivas += 1
                    if falhas_consecutivas >= max_falhas_para_parar:
                        print(f"Parando detecção após {max_falhas_para_parar} falhas consecutivas.")
                        break 
                else:
                    # Outros erros HTTP podem indicar problemas temporários ou de configuração
                    print(f"Erro ao verificar {id_dispositivo_fiware_completo}: Status {response.status_code} - {response.text}")
                    falhas_consecutivas += 1 # Considera como falha para a contagem
                    if falhas_consecutivas >= max_falhas_para_parar:
                        print(f"Parando detecção após {max_falhas_para_parar} erros/falhas consecutivas.")
                        break

            except requests.exceptions.RequestException as e:
                print(f"Erro de requisição ao verificar {id_dispositivo_fiware_completo}: {e}")
                falhas_consecutivas += 1 # Considera como falha
                if falhas_consecutivas >= max_falhas_para_parar:
                    print(f"Parando detecção após {max_falhas_para_parar} erros de requisição consecutivos.")
                    break
            
            # Atualiza o max_id_testado para a próxima vez, mesmo que falhe, para não retestar sempre do mesmo ponto
            # No entanto, isso faria com que pulasse IDs. Melhor é basear no último ID *realmente encontrado e salvo no Django*.
            # A lógica inicial de pegar o último ID do Django já faz isso.

        # Mensagens para o usuário (poderiam ser passadas via Django messages framework)
        # Por simplicidade, vamos apenas retornar para a lista de dispositivos.
        # Idealmente, você usaria `from django.contrib import messages`
        # messages.success(request, f'{dispositivos_adicionados_django} novos dispositivos adicionados.')
        # if dispositivos_encontrados_fiware == 0 and id_inicial_check > 1:
        #    messages.info(request, 'Nenhum novo dispositivo encontrado além dos já existentes.')
        # elif dispositivos_encontrados_fiware == 0:
        #    messages.info(request, 'Nenhum dispositivo encontrado na primeira varredura.')
        
        # Redireciona de volta para a lista de dispositivos
        # Você precisará importar redirect: from django.shortcuts import redirect
        # return redirect('sensores:listar_dispositivos')
        
        # Para agora, vamos apenas retornar um HttpResponse simples para indicar que terminou.
        # Em uma implementação real, você usaria o Django messages framework e redirecionaria.
        
        if dispositivos_adicionados_django > 0:
            messages.success(request, f'{dispositivos_adicionados_django} novo(s) dispositivo(s) detectado(s) e adicionado(s) ao sistema.')
            # Adiciona uma mensagem para configurar a localização
            if dispositivos_adicionados_django == 1:
                messages.info(request, "Lembre-se de configurar a localização do novo dispositivo para melhor visualização no mapa.")
            else:
                messages.info(request, "Lembre-se de configurar a localização dos novos dispositivos para melhor visualização no mapa.")
        elif dispositivos_encontrados_fiware > 0 and dispositivos_adicionados_django == 0:
            messages.info(request, 'Todos os dispositivos detectados no Fiware já existem no sistema.')
        else: # Nenhum dispositivo encontrado no Fiware na faixa testada
            messages.info(request, f'Nenhum novo dispositivo encontrado na faixa de IDs testada a partir de {str(id_inicial_check).zfill(3)}.')
            
        return redirect('sensores:listar_dispositivos')

    # Se não for POST, apenas redireciona ou mostra um erro simples
    return redirect('sensores:listar_dispositivos')

# ---
# Script de exemplo para criar/atualizar dispositivos ESP32 de teste via shell Django:
#
# from sensores.models import Dispositivo
# Dispositivo.objects.update_or_create(
#     id_dispositivo_fiware='esp32_parque_carmo',
#     defaults={
#         'nome_dispositivo': 'ESP32 Parque do Carmo',
#         'localizacao_latitude': -23.5695,
#         'localizacao_longitude': -46.4847,
#         'descricao': 'Sensor próximo ao Parque do Carmo',
#         'ativo': True
#     }
# )
# Dispositivo.objects.update_or_create(
#     id_dispositivo_fiware='esp32_pinheiros',
#     defaults={
#         'nome_dispositivo': 'ESP32 Pinheiros',
#         'localizacao_latitude': -23.5614,
#         'localizacao_longitude': -46.6794,
#         'descricao': 'Sensor no bairro de Pinheiros',
#         'ativo': True
#     }
# )
# Dispositivo.objects.update_or_create(
#     id_dispositivo_fiware='esp32_morumbi',
#     defaults={
#         'nome_dispositivo': 'ESP32 Morumbi',
#         'localizacao_latitude': -23.6010,
#         'localizacao_longitude': -46.7156,
#         'descricao': 'Sensor no bairro do Morumbi',
#         'ativo': True
#     }
# )
# ---

# Helper function to extract and format Fiware data, also recalculates status
# This can be called by both detalhes_dispositivo and the new JSON endpoint
def get_fiware_data_and_status(id_dispositivo_fiware, dispositivo_obj=None):
    if dispositivo_obj is None: # Se o objeto dispositivo não for passado, busca-o
        try:
            dispositivo_obj = Dispositivo.objects.get(id_dispositivo_fiware=id_dispositivo_fiware)
        except Dispositivo.DoesNotExist:
            return {"erro": "Dispositivo não encontrado no banco de dados local.", "dados_sensores": [], "status_operacional": "Desconhecido", "status_calculado_nivel_agua": "Desconhecido"}

    SENSOR_NOME_TRADUZIDO_HELPER = {
        'humidity': 'Umidade',
        'temperature': 'Temperatura',
        'waterLevel': 'Nível de água',
    }
    nome_sensor_nivel_agua_key = 'waterLevel' # Chave original do Fiware para nível da água

    dados_fiware_brutos = {}
    dados_sensores_formatados = []
    status_operacional_calculado = 'Offline' # Default
    status_nivel_agua_calculado = 'normal'  # Default
    timestamp_geral_fiware_iso = None
    erro_comunicacao = None

    timestamp_mais_recente_fiware = None # Para calcular status operacional

    try:
        fiware_url = f"http://20.55.19.44:1026/v2/entities/{id_dispositivo_fiware}"
        headers = {
            'Accept': 'application/json',
            'fiware-service': 'smart',
            'fiware-servicepath': '/'
        }
        response = requests.get(fiware_url, headers=headers, timeout=5)
        response.raise_for_status()
        dados_fiware_brutos = response.json()

        # Extrair timestamp geral da entidade Fiware
        timestamp_geral_str = None
        if 'TimeInstant' in dados_fiware_brutos and isinstance(dados_fiware_brutos['TimeInstant'], dict) and 'value' in dados_fiware_brutos['TimeInstant']:
            timestamp_geral_str = dados_fiware_brutos['TimeInstant']['value']
        elif 'timestamp' in dados_fiware_brutos and isinstance(dados_fiware_brutos['timestamp'], dict) and 'value' in dados_fiware_brutos['timestamp']:
            timestamp_geral_str = dados_fiware_brutos['timestamp']['value']
        
        if timestamp_geral_str:
            parsed_ts_geral = parse_timestamp(timestamp_geral_str)
            if parsed_ts_geral:
                timestamp_geral_fiware_iso = parsed_ts_geral.isoformat()
                timestamp_mais_recente_fiware = parsed_ts_geral # Inicializa com o timestamp geral

        valor_nivel_agua_fiware = None

        for attr_name, attr_data in dados_fiware_brutos.items():
            if attr_name in ['id', 'type', 'TimeInstant', 'timestamp', 'TimeInstantParsed', 'timestampParsed', 'location', 'erro_fiware'] or \
               not isinstance(attr_data, dict) or 'value' not in attr_data:
                continue

            valor = attr_data.get('value')
            unidade = None
            timestamp_attr_dt = None
            timestamp_attr_iso = None

            if isinstance(attr_data.get('metadata'), dict):
                meta = attr_data['metadata']
                if isinstance(meta.get('unitCode'), dict) and 'value' in meta['unitCode']:
                    unidade = meta['unitCode']['value']
                elif isinstance(meta.get('unit'), dict) and 'value' in meta['unit']:
                    unidade = meta['unit']['value']
                
                if isinstance(meta.get('TimeInstant'), dict) and 'value' in meta['TimeInstant']:
                    timestamp_attr_str = meta['TimeInstant']['value']
                    timestamp_attr_dt = parse_timestamp(timestamp_attr_str)
                    if timestamp_attr_dt:
                        timestamp_attr_iso = timestamp_attr_dt.isoformat()
                        # Atualiza o timestamp mais recente geral se este atributo for mais novo
                        if timestamp_mais_recente_fiware is None or timestamp_attr_dt > timestamp_mais_recente_fiware:
                            timestamp_mais_recente_fiware = timestamp_attr_dt
            
            if unidade is None: # Fallback de unidade
                if 'temperature' in attr_name.lower(): unidade = '°C'
                elif 'humidity' in attr_name.lower(): unidade = '%'
                elif 'waterlevel' in attr_name.lower(): unidade = '%'
            
            nome_exibicao = SENSOR_NOME_TRADUZIDO_HELPER.get(attr_name, attr_name.replace('_', ' ').capitalize())
            
            dados_sensores_formatados.append({
                'nome': nome_exibicao,
                'valor': valor,
                'unidade': unidade,
                'timestamp_dt_iso': timestamp_attr_iso if timestamp_attr_iso else timestamp_geral_fiware_iso, # Usa timestamp do atributo ou geral
                'nome_original': attr_name 
            })

            if attr_name == nome_sensor_nivel_agua_key and isinstance(valor, (int, float)):
                valor_nivel_agua_fiware = float(valor)

        # Calcular status_calculado_nivel_agua com base nos dados do Fiware
        if valor_nivel_agua_fiware is not None:
            if valor_nivel_agua_fiware > 80:
                status_nivel_agua_calculado = 'critical'
            elif valor_nivel_agua_fiware > 50:
                status_nivel_agua_calculado = 'moderate'
            else:
                status_nivel_agua_calculado = 'normal'
        else:
            status_nivel_agua_calculado = 'unknown' # Se não houver waterLevel nos dados do Fiware

        # Calcular status_operacional com base no timestamp mais recente do Fiware
        if timestamp_mais_recente_fiware:
            limite_inatividade = timedelta(hours=2)
            agora_utc = timezone.now() # Já é UTC
            if (agora_utc - timestamp_mais_recente_fiware) < limite_inatividade:
                status_operacional_calculado = 'Online'
        
        # Opcional: Salvar os dados recém-buscados do Fiware no banco de dados local (como em detalhes_dispositivo)
        # Esta parte pode ser adicionada aqui se desejado, seguindo a lógica de detalhes_dispositivo.
        # Por simplicidade, para o endpoint JSON, vamos focar em retornar os dados frescos.
        # A view detalhes_dispositivo já faz esse salvamento quando a página é carregada.
        # Se o polling for frequente, pode não ser necessário salvar a cada chamada JSON.

    except requests.exceptions.RequestException as e:
        erro_comunicacao = f"Erro de comunicação com o Fiware: {str(e)}"
    except json.JSONDecodeError:
        erro_comunicacao = "Erro ao decodificar a resposta JSON do Fiware."
    except Exception as e:
        erro_comunicacao = f"Um erro inesperado ocorreu: {str(e)}"

    return {
        "erro": erro_comunicacao, # Será None se não houver erro
        "dados_sensores": dados_sensores_formatados,
        "status_operacional": status_operacional_calculado,
        "status_calculado_nivel_agua": status_nivel_agua_calculado,
        "timestamp_geral_fiware_iso": timestamp_geral_fiware_iso,
        # Adicionar ID do dispositivo para confirmação no frontend
        "id_dispositivo_fiware": id_dispositivo_fiware 
    }

def dados_dispositivo_json(request, id_dispositivo_fiware):
    # A função get_object_or_404 não é necessária aqui pois get_fiware_data_and_status já lida com Dispositivo.DoesNotExist
    # No entanto, é bom validar que o dispositivo existe no nosso BD se a lógica de get_fiware_data_and_status for modificada.
    # Por enquanto, confiamos que get_fiware_data_and_status retornará um erro se o dispositivo não for encontrado no BD.
    data = get_fiware_data_and_status(id_dispositivo_fiware)
    
    if data.get("erro") and "Dispositivo não encontrado" in data["erro"]:
        return JsonResponse(data, status=404)
    elif data.get("erro"): # Outros erros de comunicação ou processamento
        return JsonResponse(data, status=500)
        
    return JsonResponse(data)

def api_listar_dispositivos_status(request):
    dispositivos_list = Dispositivo.objects.all().order_by('nome_dispositivo')
    
    dados_para_api = []

    for dispositivo in dispositivos_list:
        # Busca dados frescos do Fiware para este dispositivo
        dados_fiware = get_fiware_data_and_status(dispositivo.id_dispositivo_fiware, dispositivo_obj=dispositivo)

        # Prepara as últimas leituras formatadas a partir dos dados do Fiware
        # (get_fiware_data_and_status já retorna 'dados_sensores' formatados)
        ultimas_leituras_formatadas_fiware = {}
        if dados_fiware.get("dados_sensores"):
            for sensor_data in dados_fiware["dados_sensores"]:
                # Usar 'nome_original' se disponível e fizer sentido para o frontend, 
                # ou 'nome' (nome de exibição)
                chave_sensor = sensor_data.get('nome_original', sensor_data.get('nome', 'desconhecido'))
                ultimas_leituras_formatadas_fiware[chave_sensor] = {
                    'nome_exibicao': sensor_data.get('nome'),
                    'valor': sensor_data.get('valor'),
                    'unidade_medida': sensor_data.get('unidade'),
                    'timestamp_leitura_iso': sensor_data.get('timestamp_dt_iso')
                }

        dados_dispositivo_atual = {
            'id_dispositivo_fiware': dispositivo.id_dispositivo_fiware,
            'nome_dispositivo': dispositivo.nome_dispositivo,
            'status_operacional': dados_fiware.get('status_operacional', 'Desconhecido'),
            'status_nivel_agua': dados_fiware.get('status_calculado_nivel_agua', 'unknown'), # 'unknown' como fallback
            'timestamp_ultimo_registro_iso': dados_fiware.get('timestamp_geral_fiware_iso'),
            'ultimas_leituras': ultimas_leituras_formatadas_fiware,
            'localizacao_latitude': dispositivo.localizacao_latitude,
            'localizacao_longitude': dispositivo.localizacao_longitude,
            'descricao': dispositivo.descricao,
            'ativo_admin': dispositivo.ativo, # Status administrativo do Django
            'erro_fiware': dados_fiware.get('erro') # Para informar o frontend sobre possíveis falhas
        }
        dados_para_api.append(dados_dispositivo_atual)

    return JsonResponse({'dispositivos': dados_para_api})

def api_mapa_dispositivos_status(request):
    dispositivos_ativos = Dispositivo.objects.filter(ativo=True).order_by('nome_dispositivo')
    
    dispositivos_map_data_api = []

    for disp in dispositivos_ativos:
        # Busca dados frescos do Fiware para este dispositivo
        dados_fiware = get_fiware_data_and_status(disp.id_dispositivo_fiware, dispositivo_obj=disp)

        # Formata as últimas leituras detalhadas para o popup do mapa
        # (get_fiware_data_and_status já retorna 'dados_sensores' formatados)
        ultimas_leituras_popup = []
        if dados_fiware.get("dados_sensores"):
            for sensor_data in dados_fiware["dados_sensores"]:
                ultimas_leituras_popup.append({
                    'nome_sensor': sensor_data.get('nome'), # Nome de exibição
                    'valor': sensor_data.get('valor'),
                    'unidade_medida': sensor_data.get('unidade'),
                    'timestamp_leitura_iso': sensor_data.get('timestamp_dt_iso'),
                    'nome_original': sensor_data.get('nome_original')
                })
        
        # Determina o texto do status do nível da água com base no código de status do Fiware
        status_nivel_agua_fiware_code = dados_fiware.get('status_calculado_nivel_agua', 'unknown')
        status_nivel_agua_texto_mapa = 'Normal' # Default
        if status_nivel_agua_fiware_code == 'critical':
            status_nivel_agua_texto_mapa = 'Crítico'
        elif status_nivel_agua_fiware_code == 'moderate':
            status_nivel_agua_texto_mapa = 'Moderado'
        elif status_nivel_agua_fiware_code == 'unknown':
            status_nivel_agua_texto_mapa = 'Indefinido'
        
        # Monta os dados para a API do mapa
        dispositivos_map_data_api.append({
            'id_dispositivo_fiware': disp.id_dispositivo_fiware,
            'nome': disp.nome_dispositivo,
            'latitude': disp.localizacao_latitude,
            'longitude': disp.localizacao_longitude,
            'descricao': disp.descricao or "Sem descrição.",
            'ultimas_leituras_detalhadas': ultimas_leituras_popup,
            'status_marcador_code': status_nivel_agua_fiware_code, 
            'status_nivel_agua_texto': status_nivel_agua_texto_mapa,
            'status_operacional': dados_fiware.get('status_operacional', 'Desconhecido'), 
            'timestamp_geral_iso': dados_fiware.get('timestamp_geral_fiware_iso'),
            'erro_fiware': dados_fiware.get('erro') # Para debug ou info no frontend
        })

    return JsonResponse({'dispositivos': dispositivos_map_data_api})
