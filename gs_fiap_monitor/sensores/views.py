from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db import transaction # Para garantir atomicidade nas operações de banco
import json
from datetime import datetime
from collections import defaultdict

import plotly.express as px
import pandas as pd

from .models import Dispositivo, TipoSensor, LeituraSensor

# Função auxiliar para tentar parsear timestamps
def parse_timestamp(timestamp_str):
    if not timestamp_str:
        return timezone.now()
    try:
        # Tenta o formato ISO 8601 com Z (UTC)
        return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
    except ValueError:
        try:
            # Tenta outros formatos comuns se necessário, ou apenas retorna o padrão
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

            # O Fiware geralmente envia um objeto com uma chave 'data' que é uma lista de entidades
            entities_data = payload.get('data')
            if not isinstance(entities_data, list):
                print("Erro: Formato de payload inesperado. Esperava uma lista de entidades em 'data'.")
                return HttpResponse("Erro: Payload malformado, 'data' não é uma lista.", status=400)

            with transaction.atomic(): # Garante que todas as leituras de uma notificação são salvas ou nenhuma é.
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
                        defaults={'nome_dispositivo': device_fiware_id, 'descricao': f"Dispositivo {entity_type or 'Desconhecido'}"} 
                    )
                    if created:
                        print(f"Dispositivo '{dispositivo.nome_dispositivo}' criado.")

                    # Extrai o timestamp da leitura da entidade. FIWARE pode ter um atributo de metadados.
                    # Procurando por um atributo comum como 'timestamp' ou 'TimeInstant' em metadados
                    # Este é um ponto que pode precisar de ajuste fino baseado no formato exato do seu payload NGSI
                    timestamp_leitura_str = None
                    if 'timestamp' in entity and isinstance(entity['timestamp'], dict) and 'value' in entity['timestamp']:
                        timestamp_leitura_str = entity['timestamp']['value']
                    elif 'TimeInstant' in entity and isinstance(entity['TimeInstant'], dict) and 'value' in entity['TimeInstant']:
                        timestamp_leitura_str = entity['TimeInstant']['value']
                    # Adicione mais verificações se o timestamp vier de outro lugar

                    timestamp_leitura = parse_timestamp(timestamp_leitura_str)

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
    
    nome_sensor_nivel_agua = 'NivelAgua' # ATENÇÃO: Ajuste este nome se necessário

    SENSOR_NOME_TRADUZIDO = {
        'humidity': 'Umidade',
        'temperature': 'Temperatura',
        'waterLevel': 'Nível de água',
        'NivelAgua': 'Nível de água',
    }

    for dispositivo in dispositivos_list:
        dispositivo.ultimas_leituras_dict = {}
        tipos_sensores_usados_ids = LeituraSensor.objects.filter(dispositivo=dispositivo).values_list('tipo_sensor_id', flat=True).distinct()
        tipos_sensores_usados = TipoSensor.objects.filter(id__in=tipos_sensores_usados_ids)

        ultima_leitura_nivel_agua = None

        for tipo_sensor in tipos_sensores_usados:
            ultima_leitura = LeituraSensor.objects.filter(dispositivo=dispositivo, tipo_sensor=tipo_sensor).order_by('-timestamp_leitura').first()
            if ultima_leitura:
                nome_traduzido = SENSOR_NOME_TRADUZIDO.get(tipo_sensor.nome, tipo_sensor.nome)
                dispositivo.ultimas_leituras_dict[nome_traduzido] = {
                    'valor': ultima_leitura.valor,
                    'unidade_medida': tipo_sensor.unidade_medida,
                    'timestamp_leitura': ultima_leitura.timestamp_leitura,
                    'object': ultima_leitura
                }
                if tipo_sensor.nome == nome_sensor_nivel_agua:
                    ultima_leitura_nivel_agua = ultima_leitura.valor
        
        # Determinar status do dispositivo
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
    nome_sensor_nivel_agua = 'NivelAgua' # ATENÇÃO: Ajuste este nome se necessário

    for disp in dispositivos_ativos:
        ultimas_leituras_dict = {}
        tipos_sensores_usados_ids = LeituraSensor.objects.filter(dispositivo=disp).values_list('tipo_sensor_id', flat=True).distinct()
        tipos_sensores_usados = TipoSensor.objects.filter(id__in=tipos_sensores_usados_ids)
        
        ultima_leitura_nivel_agua_valor = None

        for ts in tipos_sensores_usados:
            ultima_leitura = LeituraSensor.objects.filter(dispositivo=disp, tipo_sensor=ts).order_by('-timestamp_leitura').first()
            if ultima_leitura:
                ultimas_leituras_dict[ts.nome] = {
                    'valor': ultima_leitura.valor,
                    'unidade': ts.unidade_medida,
                    'timestamp': ultima_leitura.timestamp_leitura.strftime('%d/%m/%Y %H:%M')
                }
                if ts.nome == nome_sensor_nivel_agua:
                    ultima_leitura_nivel_agua_valor = ultima_leitura.valor
        
        status_dispositivo = 'normal' # Default
        if ultima_leitura_nivel_agua_valor is not None:
            try:
                valor_nivel = float(ultima_leitura_nivel_agua_valor)
                if valor_nivel > 80:
                    status_dispositivo = 'critical'
                elif valor_nivel > 50:
                    status_dispositivo = 'moderate'
            except ValueError:
                print(f"Valor não numérico para {nome_sensor_nivel_agua} no dispositivo {disp.nome_dispositivo}: {ultima_leitura_nivel_agua_valor}")

        dispositivos_map_data.append({
            'id': disp.id_dispositivo_fiware,
            'nome': disp.nome_dispositivo,
            'latitude': disp.localizacao_latitude,
            'longitude': disp.localizacao_longitude,
            'descricao': disp.descricao,
            'leituras': ultimas_leituras_dict,
            'status': status_dispositivo
        })

    context = {
        'pagina_atual': 'mapa',
        'dispositivos_map_data': dispositivos_map_data
    }
    return render(request, 'sensores/mapa_interativo.html', context)

def detalhes_dispositivo(request, id_dispositivo_fiware):
    dispositivo = get_object_or_404(Dispositivo, id_dispositivo_fiware=id_dispositivo_fiware)
    leituras = LeituraSensor.objects.filter(dispositivo=dispositivo).order_by('tipo_sensor__nome', 'timestamp_leitura')

    # Lógica para determinar o status do dispositivo (baseado em NivelAgua)
    nome_sensor_nivel_agua = 'NivelAgua' # Ajuste se necessário
    ultima_leitura_nivel_agua_obj = LeituraSensor.objects.filter(
        dispositivo=dispositivo, 
        tipo_sensor__nome=nome_sensor_nivel_agua
    ).order_by('-timestamp_leitura').first()

    dispositivo.status_calculado = 'normal' # Default
    if ultima_leitura_nivel_agua_obj and isinstance(ultima_leitura_nivel_agua_obj.valor, (int, float)):
        valor_nivel = float(ultima_leitura_nivel_agua_obj.valor)
        if valor_nivel > 80:
            dispositivo.status_calculado = 'critical'
        elif valor_nivel > 50:
            dispositivo.status_calculado = 'moderate'
    elif ultima_leitura_nivel_agua_obj: # Se existe, mas o valor não é numérico
        print(f"Valor não numérico para {nome_sensor_nivel_agua} no dispositivo {dispositivo.nome_dispositivo}: {ultima_leitura_nivel_agua_obj.valor} na página de detalhes.")
        dispositivo.status_calculado = 'unknown' # Ou algum outro status que indique dado inválido

    # Dicionário de tradução dos nomes dos sensores
    SENSOR_NOME_TRADUZIDO = {
        'humidity': 'Umidade',
        'temperature': 'Temperatura',
        'waterLevel': 'Nível de água',
        'NivelAgua': 'Nível de água',
    }

    leituras_por_sensor = defaultdict(lambda: {'timestamps': [], 'valores': [], 'unidade': ''})

    if leituras:
        for leitura in leituras:
            nome_sensor = leitura.tipo_sensor.nome
            leituras_por_sensor[nome_sensor]['timestamps'].append(leitura.timestamp_leitura)
            leituras_por_sensor[nome_sensor]['valores'].append(leitura.valor)
            if not leituras_por_sensor[nome_sensor]['unidade']: # Pega a unidade da primeira leitura (devem ser iguais)
                leituras_por_sensor[nome_sensor]['unidade'] = leitura.tipo_sensor.unidade_medida
    
    graficos_html = {}
    for nome_sensor, dados in leituras_por_sensor.items():
        nome_traduzido = SENSOR_NOME_TRADUZIDO.get(nome_sensor, nome_sensor)
        if dados['timestamps'] and dados['valores']:
            # Criar DataFrame para Plotly
            df = pd.DataFrame({
                'Timestamp': dados['timestamps'],
                'Valor': dados['valores']
            })
            fig = px.line(df, x='Timestamp', y='Valor', title=f"Histórico de Leituras - {nome_traduzido} ({dados['unidade']})")
            fig.update_layout(
                xaxis_title="Data e Hora da Leitura",
                yaxis_title=f"Valor ({dados['unidade']})",
                title_x=0.5, # Centralizar título
                plot_bgcolor='rgba(249, 250, 251, 1)', # bg-gray-50
                paper_bgcolor='rgba(255, 255, 255, 1)', # bg-white
                font=dict(family="Roboto, sans-serif", size=12, color="#333333"),
                margin=dict(l=40, r=40, t=60, b=40)
            )
            fig.update_xaxes(
                showline=True, linewidth=1, linecolor='rgb(204, 204, 204)',
                showgrid=True, gridwidth=1, gridcolor='rgb(230, 230, 230)'
            )
            fig.update_yaxes(
                showline=True, linewidth=1, linecolor='rgb(204, 204, 204)',
                showgrid=True, gridwidth=1, gridcolor='rgb(230, 230, 230)'
            )
            fig.update_traces(line=dict(color='#b0dcfc', width=2)) # Cor primária do tema
            
            # Adicionar marcadores para melhor visualização dos pontos
            fig.update_traces(mode='lines+markers', marker=dict(size=5, color='#333333'))

            grafico_html = fig.to_html(full_html=False, include_plotlyjs='cdn', default_height='450px')
            graficos_html[nome_traduzido] = grafico_html
        else:
            graficos_html[nome_traduzido] = "<p class=\"italic text-gray-500\">Não há dados suficientes para gerar o gráfico para este sensor.</p>"


    context = {
        'dispositivo': dispositivo,
        'graficos_html': graficos_html,
        'pagina_atual': 'detalhes_dispositivo' 
    }
    return render(request, 'sensores/detalhes_dispositivo.html', context)
