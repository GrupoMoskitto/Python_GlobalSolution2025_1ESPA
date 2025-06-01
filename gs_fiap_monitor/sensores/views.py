from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db import transaction
import json
from datetime import datetime, timedelta
from collections import defaultdict
import requests # Adicionado import
from django.contrib import messages # Adicionar este import no topo do arquivo views.py
from django.urls import reverse, NoReverseMatch

import plotly.express as px
import pandas as pd

from .models import Dispositivo, TipoSensor, LeituraSensor
from .forms import DispositivoLocalizacaoForm # Adicionado import do novo formulário

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
                    # Usaremos o id_dispositivo_fiware como nome_dispositivo se um nome específico não for enviado
                    dispositivo, created = Dispositivo.objects.get_or_create(
                        id_dispositivo_fiware=device_fiware_id,
                        defaults={ 'nome_dispositivo': device_fiware_id, 'descricao': f"Dispositivo {entity_type or 'Desconhecido'}"}
                    )
                    if created:
                        print(f"Dispositivo '{dispositivo.nome_dispositivo}' criado.")

                    # Extrai o timestamp da leitura da entidade.
                    timestamp_leitura_str = None
                    print(f"[FIWARE NOTIFICATION - TS DEBUG] Entidade completa: {entity}")
                    if 'timestamp' in entity and isinstance(entity['timestamp'], dict) and 'value' in entity['timestamp']:
                        timestamp_leitura_str = entity['timestamp']['value']
                        print(f"[FIWARE NOTIFICATION - TS DEBUG] Timestamp extraído de entity[timestamp][value]: '{timestamp_leitura_str}'")
                    elif 'TimeInstant' in entity and isinstance(entity['TimeInstant'], dict) and 'value' in entity['TimeInstant']:
                        timestamp_leitura_str = entity['TimeInstant']['value']
                        print(f"[FIWARE NOTIFICATION - TS DEBUG] Timestamp extraído de entity[TimeInstant][value]: '{timestamp_leitura_str}'")
                    elif 'TimeInstant' in entity and isinstance(entity['TimeInstant'], str):
                        timestamp_leitura_str = entity['TimeInstant']
                        print(f"[FIWARE NOTIFICATION - TS DEBUG] Timestamp extraído de entity[TimeInstant] (string): '{timestamp_leitura_str}'")
                    elif 'timestamp' in entity and isinstance(entity['timestamp'], str):
                        timestamp_leitura_str = entity['timestamp']
                        print(f"[FIWARE NOTIFICATION - TS DEBUG] Timestamp extraído de entity[timestamp] (string): '{timestamp_leitura_str}'")
                    else:
                        print(f"[FIWARE NOTIFICATION - TS DEBUG] NENHUM timestamp padrão encontrado na raiz da entidade. Verificando metadados...")
                        # Tentar encontrar em metadados de algum atributo (ex: dateObserved)
                        for attr_name, attr_data in entity.items():
                            if isinstance(attr_data, dict) and 'metadata' in attr_data:
                                if 'TimeInstant' in attr_data['metadata'] and 'value' in attr_data['metadata']['TimeInstant']:
                                    timestamp_leitura_str = attr_data['metadata']['TimeInstant']['value']
                                    print(f"[FIWARE NOTIFICATION - TS DEBUG] Timestamp extraído de metadata.TimeInstant.value do atributo '{attr_name}': '{timestamp_leitura_str}'")
                                    break
                                if 'timestamp' in attr_data['metadata'] and 'value' in attr_data['metadata']['timestamp']:
                                    timestamp_leitura_str = attr_data['metadata']['timestamp']['value']
                                    print(f"[FIWARE NOTIFICATION - TS DEBUG] Timestamp extraído de metadata.timestamp.value do atributo '{attr_name}': '{timestamp_leitura_str}'")
                                    break
                    
                    if timestamp_leitura_str:
                        print(f"[FIWARE NOTIFICATION - TS DEBUG] Valor de timestamp_leitura_str ANTES de parse_timestamp: '{timestamp_leitura_str}'")
                        timestamp_leitura = parse_timestamp(timestamp_leitura_str)
                        print(f"[FIWARE NOTIFICATION - TS DEBUG] Valor de timestamp_leitura DEPOIS de parse_timestamp: {timestamp_leitura}")
                    else:
                        print(f"[FIWARE NOTIFICATION - TS DEBUG] Nenhum timestamp encontrado para a entidade '{device_fiware_id}'. Usando timezone.now().")
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
                            if created_type:
                                print(f"TipoSensor '{tipo_sensor.nome}' ('{tipo_sensor.unidade_medida}') criado.")
                            elif tipo_sensor.unidade_medida == 'Desconhecida' and unidade != 'Desconhecida':
                                # Atualiza a unidade se encontrarmos uma e antes era desconhecida
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
                            print(f"Leitura salva: {dispositivo.nome_dispositivo} - {tipo_sensor.nome}: {attr_value} {tipo_sensor.unidade_medida}")
                        elif attr_value is not None:
                            print(f"Atributo '{attr_name}' com valor não numérico '{attr_value}' ignorado como leitura de sensor.")

            return HttpResponse("Notificação processada com sucesso.", status=200)
        except json.JSONDecodeError:
            return HttpResponse("Erro: JSON inválido.", status=400)
        except Exception as e:
            print(f"Erro crítico ao processar notificação: {e}")
            # Em produção, logar o traceback completo aqui seria importante
            # import traceback
            # print(traceback.format_exc())
            return HttpResponse(f"Erro interno ao processar notificação: {str(e)}", status=500)
    else:
        return HttpResponse("Método não permitido. Use POST.", status=405)

def listar_dispositivos(request):
    dispositivos_list = Dispositivo.objects.all().order_by('nome_dispositivo')
    
    nome_sensor_nivel_agua = 'waterLevel' # ATENÇÃO: Ajuste este nome se necessário

    SENSOR_NOME_TRADUZIDO = {
        'humidity': 'Umidade',
        'temperature': 'Temperatura',
        'waterLevel': 'Nível de água',
        'waterLevel': 'Nível de água',
    }

    for dispositivo in dispositivos_list:
        dispositivo.ultimas_leituras_dict = {}
        tipos_sensores_usados_ids = LeituraSensor.objects.filter(dispositivo=dispositivo).values_list('tipo_sensor_id', flat=True).distinct()
        tipos_sensores_usados = TipoSensor.objects.filter(id__in=tipos_sensores_usados_ids)

        ultima_leitura_nivel_agua = None
        timestamp_mais_recente_geral = None # Para status operacional

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
        
        # Determinar status do dispositivo (baseado em waterLevel)
        dispositivo.status = 'normal' # Default
        if ultima_leitura_nivel_agua is not None:
            try:
                valor_nivel = float(ultima_leitura_nivel_agua)
                if valor_nivel > 80:
                    dispositivo.status = 'critical'
                elif valor_nivel > 50:
                    dispositivo.status = 'moderate'
            except ValueError:
                print(f"Valor não numérico para {nome_sensor_nivel_agua} no dispositivo {dispositivo.nome_dispositivo}: {ultima_leitura_nivel_agua}")
                # Mantém status como 'normal' ou poderia ser um status de erro/desconhecido

        # Determinar status operacional (Online/Offline)
        dispositivo.status_operacional = 'Offline' # Default
        if timestamp_mais_recente_geral:
            limite_inatividade = timedelta(hours=2) # Limite de 2 horas
            agora_utc = timezone.now()
            if (agora_utc - timestamp_mais_recente_geral) < limite_inatividade:
                dispositivo.status_operacional = 'Online'
            else:
                print(f"[Listar Dispositivos] {dispositivo.nome_dispositivo} OFFLINE. Última leitura: {timestamp_mais_recente_geral} (UTC), Agora: {agora_utc} (UTC)")
        else:
            print(f"[Listar Dispositivos] {dispositivo.nome_dispositivo} OFFLINE (sem leituras).")

    context = {
        'dispositivos': dispositivos_list,
        'pagina_atual': 'listar_dispositivos' # Adicionado para consistência
    }
    return render(request, 'sensores/listar_dispositivos.html', context)

# View para a home page simplificada
def home_page(request):
    context = {
        'pagina_atual': 'home',
        # Outros dados que a home page possa precisar no futuro (ex: notícias, estatísticas gerais)
    }
    return render(request, 'sensores/home.html', context)

# View para a nova página do mapa interativo
def mapa_interativo_view(request):
    dispositivos_ativos = Dispositivo.objects.filter(ativo=True).order_by('nome_dispositivo')
    
    dispositivos_map_data = []
    nome_sensor_nivel_agua = 'waterLevel' # ATENÇÃO: Ajuste este nome se necessário
    SENSOR_NOME_TRADUZIDO_MAPA = {
        'humidity': 'Umidade',
        'temperature': 'Temperatura',
        'waterLevel': 'Nível de Água', # Consistência na capitalização
        # Adicione outros sensores se necessário
    }

    for disp in dispositivos_ativos:
        ultimas_leituras_formatadas = {} # Usaremos este para o popup, com nomes traduzidos
        tipos_sensores_usados_ids = LeituraSensor.objects.filter(dispositivo=disp).values_list('tipo_sensor_id', flat=True).distinct()
        tipos_sensores_usados = TipoSensor.objects.filter(id__in=tipos_sensores_usados_ids)
        
        ultima_leitura_nivel_agua_valor = None
        timestamp_mais_recente_geral = None # Para status operacional

        for ts in tipos_sensores_usados:
            ultima_leitura = LeituraSensor.objects.filter(dispositivo=disp, tipo_sensor=ts).order_by('-timestamp_leitura').first()
            if ultima_leitura:
                nome_traduzido = SENSOR_NOME_TRADUZIDO_MAPA.get(ts.nome, ts.nome)
                ultimas_leituras_formatadas[nome_traduzido] = (
                    f"{ultima_leitura.valor} {ts.unidade_medida} "
                    f"<span class='text-xs text-gray-500'>({ultima_leitura.timestamp_leitura.strftime('%d/%m %H:%M')})</span>"
                )
                if ts.nome == nome_sensor_nivel_agua:
                    ultima_leitura_nivel_agua_valor = ultima_leitura.valor
                
                if timestamp_mais_recente_geral is None or ultima_leitura.timestamp_leitura > timestamp_mais_recente_geral:
                    timestamp_mais_recente_geral = ultima_leitura.timestamp_leitura
        
        status_dispositivo_fiware = 'normal' # Baseado no nível da água para o marcador
        if ultima_leitura_nivel_agua_valor is not None:
            try:
                valor_nivel = float(ultima_leitura_nivel_agua_valor)
                if valor_nivel > 80:
                    status_dispositivo_fiware = 'critical'
                elif valor_nivel > 50:
                    status_dispositivo_fiware = 'moderate'
            except ValueError:
                print(f"[Mapa Interativo] Valor não numérico para {nome_sensor_nivel_agua} no dispositivo {disp.nome_dispositivo}: {ultima_leitura_nivel_agua_valor}")

        # Determinar status operacional (Online/Offline)
        status_operacional_disp = 'Offline'
        if timestamp_mais_recente_geral:
            limite_inatividade = timedelta(hours=2) # Consistente com outras views
            agora_utc = timezone.now()
            if (agora_utc - timestamp_mais_recente_geral) < limite_inatividade:
                status_operacional_disp = 'Online'

        # Obter a URL de detalhes do dispositivo
        try:
            url_detalhes = reverse('sensores:detalhes_dispositivo', args=[disp.id_dispositivo_fiware])
        except NoReverseMatch:
            url_detalhes = "#" # Fallback se a URL não puder ser gerada
            print(f"[Mapa Interativo] Não foi possível gerar a URL de detalhes para {disp.id_dispositivo_fiware}")

        dispositivos_map_data.append({
            'id': disp.id_dispositivo_fiware,
            'nome': disp.nome_dispositivo,
            'latitude': disp.localizacao_latitude,
            'longitude': disp.localizacao_longitude,
            'descricao': disp.descricao or "Sem descrição.", # Garantir que não seja None
            'leituras_formatadas': ultimas_leituras_formatadas, # Novo campo com dados formatados
            'status_marcador': status_dispositivo_fiware, # Para a cor do marcador
            'status_operacional': status_operacional_disp, # Online/Offline
            'url_detalhes': url_detalhes
        })

    context = {
        'pagina_atual': 'mapa',
        'dispositivos_map_data': dispositivos_map_data
    }
    return render(request, 'sensores/mapa_interativo.html', context)

def detalhes_dispositivo(request, id_dispositivo_fiware):
    dispositivo = get_object_or_404(Dispositivo, id_dispositivo_fiware=id_dispositivo_fiware)
    leituras = LeituraSensor.objects.filter(dispositivo=dispositivo).order_by('tipo_sensor__nome', 'timestamp_leitura')

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
        print(f"Valor não numérico para {nome_sensor_nivel_agua} no dispositivo {dispositivo.nome_dispositivo}: {ultima_leitura_nivel_agua_obj.valor} na página de detalhes.")
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
            print(f"[Detalhes Dispositivo] {dispositivo.nome_dispositivo} OFFLINE. Última leitura BD: {timestamp_mais_recente_bd} (UTC), Agora: {agora_utc} (UTC)")
    else:
        print(f"[Detalhes Dispositivo] {dispositivo.nome_dispositivo} OFFLINE (sem leituras no BD).")

    # Buscar dados ao vivo do Fiware
    dados_fiware_live = {}
    timestamp_leitura_fiware_live = timezone.now() # Default para o momento da busca

    try:
        fiware_url = f"http://20.55.19.44:1026/v2/entities/{id_dispositivo_fiware}?type=SensorDevice&options=keyValues"
        headers = {
            'Accept': 'application/json',
            'fiware-service': 'smart',
            'fiware-servicepath': '/'
        }
        response = requests.get(fiware_url, headers=headers, timeout=5) # Adicionado timeout
        response.raise_for_status() # Levanta exceção para respostas de erro HTTP (4xx ou 5xx)
        dados_fiware_live = response.json()
        # Normalizar o timestamp se vier como um dicionário de valor (comum no Fiware sem options=keyValues)
        # Com options=keyValues, o timestamp já deve vir como valor direto se for um atributo de primeiro nível.
        # Se o timestamp estiver em metadata, precisaria de um tratamento específico.
        # Exemplo: se o timestamp for um atributo chamado 'TimeInstant' e for uma string ISO
        if 'TimeInstant' in dados_fiware_live and isinstance(dados_fiware_live['TimeInstant'], str):
            try:
                dados_fiware_live['TimeInstantParsed'] = datetime.fromisoformat(dados_fiware_live['TimeInstant'].replace('Z', '+00:00'))
                timestamp_leitura_fiware_live = dados_fiware_live['TimeInstantParsed']
            except ValueError:
                dados_fiware_live['TimeInstantParsed'] = dados_fiware_live['TimeInstant'] # Mantém como string se falhar
        elif 'timestamp' in dados_fiware_live and isinstance(dados_fiware_live['timestamp'], str): # Outro nome comum
             try:
                dados_fiware_live['timestampParsed'] = datetime.fromisoformat(dados_fiware_live['timestamp'].replace('Z', '+00:00'))
                timestamp_leitura_fiware_live = dados_fiware_live['timestampParsed']
             except ValueError:
                dados_fiware_live['timestampParsed'] = dados_fiware_live['timestamp']
        
        # >>> INÍCIO: Salvar dados do Fiware (keyValues) no banco de dados como LeituraSensor <<<
        if not dados_fiware_live.get('erro_fiware'): # Só processa se não houve erro na busca
            with transaction.atomic():
                for key, value in dados_fiware_live.items():
                    # Ignora metadados do NGSI-LD e chaves que não representam leituras diretas
                    if key in ['id', 'type', 'TimeInstant', 'TimeInstantParsed', 'timestamp', 'timestampParsed', 'location'] or not isinstance(value, (int, float, str)):
                        # Se for string, tentaremos converter para float. Se falhar, ignoramos.
                        if isinstance(value, str):
                            try:
                                value = float(value)
                            except ValueError:
                                print(f"[Detalhes Dispositivo] Atributo '{key}' com valor string não numérico '{value}' não será salvo como leitura.")
                                continue
                        else:
                            continue # Ignora se não for numérico ou string conversível

                    # Tenta obter unidade de medida (se disponível como metadado, o que não é comum com keyValues diretos)
                    # Para keyValues, a unidade geralmente não vem junto com o valor simples.
                    # Vamos assumir 'Desconhecida' ou você pode ter um mapeamento.
                    unidade_medida_padrao = '%' if key == 'humidity' or key == 'waterLevel' else '°C' if key == 'temperature' else 'Desconhecida'

                    tipo_sensor, created_ts = TipoSensor.objects.get_or_create(
                        nome=key,
                        defaults={'unidade_medida': unidade_medida_padrao, 'descricao': f"Sensor {key} (auto-registrado)"}
                    )
                    if created_ts:
                        print(f"[Detalhes Dispositivo] TipoSensor '{tipo_sensor.nome}' criado com unidade '{unidade_medida_padrao}'.")
                    
                    # Evitar duplicatas exatas (mesmo dispositivo, sensor, valor e timestamp)
                    # Esta verificação pode ser custosa. Uma alternativa é ter um UNIQUE constraint no modelo.
                    # Por simplicidade, vamos permitir dups se o timestamp for ligeiramente diferente,
                    # ou confiar que as visitas à página não serão tão frequentes para causar problemas massivos.
                    # Para uma solução mais robusta, um last_updated_fiware_data no Dispositivo seria melhor.
                    obj, created = LeituraSensor.objects.update_or_create(
                        dispositivo=dispositivo,
                        tipo_sensor=tipo_sensor,
                        timestamp_leitura=timestamp_leitura_fiware_live,
                        defaults={'valor': value}
                    )
                    if created:
                        print(f"[Detalhes Dispositivo] Leitura de '{key}' ({value}) CRIADA para o dispositivo '{dispositivo.id_dispositivo_fiware}' com timestamp '{timestamp_leitura_fiware_live}'.")
                    else:
                        print(f"[Detalhes Dispositivo] Leitura de '{key}' ({value}) ATUALIZADA para o dispositivo '{dispositivo.id_dispositivo_fiware}' com timestamp '{timestamp_leitura_fiware_live}'.")
        # >>> FIM: Salvar dados do Fiware (keyValues) no banco de dados como LeituraSensor <<<

    except requests.exceptions.RequestException as e:
        print(f"Erro ao buscar dados do Fiware para {id_dispositivo_fiware}: {e}")
        # Pode adicionar uma mensagem para o template aqui, se desejar
        dados_fiware_live['erro_fiware'] = str(e)
    except json.JSONDecodeError:
        print(f"Erro ao decodificar JSON do Fiware para {id_dispositivo_fiware}")
        dados_fiware_live['erro_fiware'] = "Resposta inválida do Fiware (JSON malformado)."

    # Dicionário de tradução dos nomes dos sensores
    SENSOR_NOME_TRADUZIDO = {
        'humidity': 'Umidade',
        'temperature': 'Temperatura',
        'waterLevel': 'Nível de água'
    }

    leituras_por_sensor = defaultdict(lambda: {'timestamps': [], 'valores': [], 'unidade': ''})
    
    # Buscando todas as leituras do BD para este dispositivo para os gráficos
    todas_leituras_db = LeituraSensor.objects.filter(dispositivo=dispositivo).order_by('tipo_sensor__nome', 'timestamp_leitura')
    print(f"[Detalhes Dispositivo - Gráficos] Encontradas {todas_leituras_db.count()} leituras no DB para {dispositivo.id_dispositivo_fiware}")

    if todas_leituras_db:
        for leitura in todas_leituras_db:
            nome_sensor = leitura.tipo_sensor.nome
            print(f"[Detalhes Dispositivo - Gráficos] Processando leitura do BD: Sensor '{nome_sensor}', Valor '{leitura.valor}', Timestamp '{leitura.timestamp_leitura}'")
            leituras_por_sensor[nome_sensor]['timestamps'].append(leitura.timestamp_leitura)
            leituras_por_sensor[nome_sensor]['valores'].append(leitura.valor)
            if not leituras_por_sensor[nome_sensor]['unidade']:
                leituras_por_sensor[nome_sensor]['unidade'] = leitura.tipo_sensor.unidade_medida
    else:
        print(f"[Detalhes Dispositivo - Gráficos] Nenhuma leitura encontrada no BD para os gráficos de {dispositivo.id_dispositivo_fiware}.")
    
    graficos_html = {}
    if not leituras_por_sensor:
        print(f"[Detalhes Dispositivo - Gráficos] Dicionário leituras_por_sensor está vazio para {dispositivo.id_dispositivo_fiware}. Nenhum gráfico será gerado.")
    else:
        for nome_sensor, dados in leituras_por_sensor.items():
            nome_traduzido = SENSOR_NOME_TRADUZIDO.get(nome_sensor, nome_sensor)
            if dados['timestamps'] and dados['valores']:
                df = pd.DataFrame({
                    'Timestamp': dados['timestamps'],
                    'Valor': dados['valores']
                })
                # AGREGAR DADOS: Calcula a média de 'Valor' para cada 'Timestamp' único
                if not df.empty:
                    df['Valor'] = pd.to_numeric(df['Valor'], errors='coerce') # Garante que 'Valor' é numérico
                    df.dropna(subset=['Valor'], inplace=True) # Remove linhas onde 'Valor' não pôde ser convertido
                    if not df.empty:
                         df = df.groupby('Timestamp', as_index=False)['Valor'].mean()
                
                if not df.empty: # Verifica se o df ainda tem dados após a agregação
                    fig = px.line(df, x='Timestamp', y='Valor', title=f"Histórico de Leituras - {nome_traduzido} ({dados['unidade']})")
                    fig.update_layout(
                        xaxis_title="Data e Hora da Leitura",
                        yaxis_title=f"Valor ({dados['unidade']})",
                        title_x=0.5, # Centralizar título
                        plot_bgcolor='rgba(249, 250, 251, 1)', # bg-gray-50
                        paper_bgcolor='rgba(255, 255, 255, 1)', # bg-white
                        font=dict(family="Roboto, sans-serif", size=12, color="#333333"),
                        margin=dict(l=40, r=40, t=60, b=40),
                        yaxis=dict(autorange=True) # Força autorange
                    )
                    # Ajuste de intervalo para gráfico com apenas um ponto
                    if len(df) == 1 and 'Valor' in df.columns and pd.api.types.is_numeric_dtype(df['Valor']):
                        val = df['Valor'].iloc[0]
                        padding = abs(val * 0.1) if val != 0 else 1.0 # 10% de preenchimento, ou 1 se valor for 0
                        fig.update_layout(yaxis_range=[val - padding, val + padding])
                    
                    fig.update_xaxes(
                        showline=True, linewidth=1, linecolor='rgb(204, 204, 204)',
                        showgrid=True, gridwidth=1, gridcolor='rgb(230, 230, 230)'
                    )
                    fig.update_yaxes(
                        showline=True, linewidth=1, linecolor='rgb(204, 204, 204)',
                        showgrid=True, gridwidth=1, gridcolor='rgb(230, 230, 230)'
                    )
                    fig.update_traces(line=dict(color='#b0dcfc', width=2))
                    fig.update_traces(mode='lines+markers', marker=dict(size=5, color='#333333'))
                    grafico_html = fig.to_html(full_html=False, include_plotlyjs='cdn', default_height='450px')
                    graficos_html[nome_traduzido] = grafico_html
                else: # Se df ficou vazio após coerção/agregação ou se não havia dados suficientes inicialmente
                    graficos_html[nome_traduzido] = "<p class=\"italic text-gray-500\">Não há dados suficientes ou válidos para gerar o gráfico para este sensor.</p>"
                    print(f"[Detalhes Dispositivo - Gráficos] Não há dados suficientes/válidos para o sensor '{nome_sensor}' (traduzido: '{nome_traduzido}') para {dispositivo.id_dispositivo_fiware} após tentativa de agregação.")

    context = {
        'dispositivo': dispositivo,
        'dados_fiware_live': dados_fiware_live, # Adicionado dados do Fiware ao contexto
        'graficos_html': graficos_html,
        'pagina_atual': 'detalhes_dispositivo' 
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
                        # Adicionar outros atributos se necessário, ex: address
                        # "address": {
                        #    "type": "Property",
                        #    "value": {
                        #        "streetAddress": "Rua Exemplo, 123",
                        #        "addressLocality": "Cidade Exemplo", 
                        #        "addressCountry": "BR"
                        #    }
                        # }
                    }
                    print(f"Enviando para Fiware URL: {fiware_url}")
                    print(f"Payload Fiware: {json.dumps(payload, indent=2)}")
                    
                    response_fiware = requests.patch(fiware_url, headers=headers, json=payload, timeout=10)
                    response_fiware.raise_for_status() # Levanta exceção para erros HTTP
                    
                    mensagem_sucesso += " E atualizada no Fiware."
                    print(f"Fiware PATCH response: {response_fiware.status_code}")
                    if response_fiware.content: # Algumas respostas PATCH bem-sucedidas podem não ter conteúdo
                         print(f"Fiware PATCH content: {response_fiware.text}")

                else:
                    # Se lat/lon foram apagados, talvez seja preciso remover o atributo location do Fiware
                    # Isso é mais complexo, pois PATCH não remove atributos com valor null diretamente fácil
                    # Poderia ser feito um GET, remover o atributo do JSON e fazer um PUT, ou usar API específica se houver.
                    # Por agora, apenas não atualizamos o Fiware se os campos estiverem vazios.
                    mensagem_sucesso += " (Localização no Fiware não atualizada pois os campos estão vazios)."

            except requests.exceptions.RequestException as e:
                print(f"Erro ao atualizar localização no Fiware para {id_dispositivo_fiware}: {e}")
                mensagem_erro_fiware = f"Localização salva no sistema, mas falha ao atualizar no Fiware: {e}"
            except Exception as e:
                print(f"Erro inesperado ao atualizar localização: {e}")
                # Tratar outros erros gerais se necessário
                # form.add_error(None, f"Erro inesperado: {e}") # Adiciona erro ao formulário
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
                print("Não foi possível parsear o último ID numérico do Fiware. Começando do 0.")
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
            fiware_url = f"http://20.55.19.44:1026/v2/entities/{id_dispositivo_fiware_completo}?type=SensorDevice"
            
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
