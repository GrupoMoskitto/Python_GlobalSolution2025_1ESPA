<p align="center">
  <img src="https://img.shields.io/badge/Django-5.2.1-green?logo=django" alt="Django"/>
  <img src="https://img.shields.io/badge/REST%20API-DRF-blue?logo=django" alt="REST"/>
  <img src="https://img.shields.io/badge/Plotly-Graphs-orange?logo=plotly" alt="Plotly"/>
</p>

<h1 align="center"><img src="gs_fiap_monitor/static/sensores/img/favicon.png" alt="Moskitto Logo" width="40" style="vertical-align: middle; margin-right: 10px;"/>  GS FIAP Monitor</h1>

> **Sistema web para monitoramento de sensores (umidade, temperatura, nível de água) integrados via ESP32 e Fiware Orion Context Broker. Visual moderno, responsivo e com gráficos interativos.**

---

## 🚀 Funcionalidades

| Funcionalidade                        | Descrição                                                                                                 |
|---------------------------------------|-----------------------------------------------------------------------------------------------------------|
| 📡 Integração Fiware                  | Recebe dados de sensores via Orion Context Broker e busca dados "ao vivo" para detalhes do dispositivo. |
| 📋 Listagem de Dispositivos           | Cards com status colorido (baseado no nível de água), últimas leituras, status operacional e link para detalhes. |
| 📈 Gráficos Interativos               | Histórico de leituras com Plotly na página de detalhes do dispositivo.                                    |
| 🗺️ Mapa Interativo                    | Localização dos dispositivos com marcadores de status, legendas e filtros. Popup com link direto para página de detalhes. |
| 📍 Edição de Localização              | Permite editar a latitude/longitude de um dispositivo, atualizando também no Fiware.                      |
| ✨ Detecção de Novos Dispositivos     | Funcionalidade para buscar e cadastrar automaticamente novos dispositivos registrados no Fiware.         |
| 🔋 Status Operacional                 | Indica se um dispositivo está Online (última leitura recente) ou Offline.                                 |
| 🔒 Administração                      | Gerenciamento fácil via Django Admin.                                                                     |
| 🎨 Visual Moderno                     | TailwindCSS, responsivo, navegação fluida.                                                                |

---


## 📦 Modelos de Dados

| Modelo           | Campos Principais                                                                                 |
|------------------|--------------------------------------------------------------------------------------------------|
| **Dispositivo**  | nome_dispositivo, id_dispositivo_fiware, localizacao_latitude, localizacao_longitude, descricao, data_criacao, ativo      |
| **TipoSensor**   | nome, unidade_medida, descricao                                                                  |
| **LeituraSensor**| dispositivo (FK), tipo_sensor (FK), valor, timestamp_leitura, timestamp_recebimento              |

### Exemplo de Dados para LeituraSensor (armazenado no BD)

```json
{
  "dispositivo": "urn:ngsi-ld:SensorDevice:001", // Referência ao Dispositivo
  "tipo_sensor": "temperature", // Referência ao TipoSensor
  "valor": 23.5,
  "timestamp_leitura": "2024-06-10T12:00:00Z"
}
```

---

## 🛠️ Tecnologias Utilizadas

| Tecnologia         | Versão    | Descrição                                 |
|--------------------|-----------|-------------------------------------------|
| Django             | 5.2.1     | Backend web framework                     |
| Django REST        | 3.16.0    | API REST                                  |
| Plotly             | 6.1.2     | Gráficos interativos                      |
| Pandas             | 2.2.3     | Manipulação de dados                      |
| Prophet            | 1.1.7     | Previsão de séries temporais              |
| Scikit-learn       | 1.6.1     | Machine Learning                          |
| Leaflet.js         | (via CDN) | Mapas interativos                         |
| TailwindCSS        | -         | Estilização moderna e responsiva          |

---

## ⚙️ Instalação e Execução

1. **Clone o repositório**
   ```bash
   git clone https://github.com/rouri404/site-gs-fiap.git
   cd site-gs-fiap
   ```
2. **Crie e ative um ambiente virtual**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   venv\Scripts\activate   # Windows
   ```
3. **Instale as dependências**
   ```bash
   pip install -r requirements.txt
   ```
4. **Aplique as migrações**
   ```bash
   python gs_fiap_monitor/manage.py migrate
   ```
5. **Crie um superusuário (opcional, para admin)**
   ```bash
   python gs_fiap_monitor/manage.py createsuperuser
   ```
6. **Execute o servidor**
   ```bash
   python gs_fiap_monitor/manage.py runserver
   ```
7. **Acesse**
   - Sistema: [http://localhost:8000/sensores/](http://localhost:8000/sensores/) (ou a URL da sua página inicial, ex: `/` se configurado no `urls.py` principal)
   - Admin: [http://localhost:8000/admin/](http://localhost:8000/admin/)

---

## 🔗 Integração com Fiware

- O endpoint `/sensores/fiware_notification/` recebe notificações NGSI do Orion Context Broker e armazena as leituras automaticamente.
- A página de detalhes de um dispositivo (`/sensores/dispositivo/<id_fiware>/`) busca dados "ao vivo" diretamente do Fiware para exibição e também os salva no banco de dados local para histórico.

### Exemplo de Payload de Notificação Aceito (NGSI v2)

```json
{
  "subscriptionId": "some-subscription-id",
  "data": [
    {
      "id": "urn:ngsi-ld:SensorDevice:001",
      "type": "SensorDevice",
      "temperature": {"value": 23.5, "type": "Number", "metadata": {"unitCode": {"value": "CEL"}}},
      "humidity": {"value": 60, "type": "Number", "metadata": {"unitCode": {"value": "P1"}}},
      "waterLevel": {"value": 45, "type": "Number", "metadata": {"unitCode": {"value": "P1"}}},
      "TimeInstant": {"value": "2025-06-01T12:00:00.000Z", "type": "DateTime"} 
    }
    // Pode haver outras entidades na mesma notificação
  ]
}
```
*Nota: O campo `TimeInstant` (ou `timestamp`) na raiz da entidade é usado para a data/hora da leitura. Se não presente, a data/hora do recebimento da notificação será usada. A unidade de medida (`unitCode`) é extraída dos metadados do atributo, se disponível.*

---

## 📊 Visualização

| Página                  | Descrição                                                                                                  |
|-------------------------|------------------------------------------------------------------------------------------------------------|
| **Listagem**            | Cards de dispositivos com status de nível de água, status operacional (Online/Offline) e últimas leituras. |
| **Detalhes**            | Informações completas do dispositivo, dados "ao vivo" do Fiware e gráficos interativos (Plotly) do histórico. |
| **Mapa**                | Dispositivos geolocalizados com marcadores de status. Popups com informações resumidas e link para a página de detalhes. |
| **Admin**               | Gerenciamento de dispositivos, tipos de sensores e leituras.                                               |

---

## 🧑‍💻 Contribuição

1. Faça um fork do projeto
2. Crie uma branch (`git checkout -b feature/sua-feature`)
3. Commit suas alterações (`git commit -am 'feat: nova feature'`)
4. Push para o branch (`git push origin feature/sua-feature`)
5. Abra um Pull Request

## 🛰️ Como Adicionar e Configurar Dispositivos ESP32

Dispositivos são primariamente detectados automaticamente através da funcionalidade "Detectar Novos Dispositivos" na página de listagem, que consulta o Fiware por novos IDs `urn:ngsi-ld:SensorDevice:XXX`.

Você também pode cadastrar e configurar dispositivos manualmente:

### 1. Via Django Admin

1. Acesse o painel de administração: `http://localhost:8000/admin/`
2. Clique em **Dispositivos**.
3. Clique em **Adicionar Dispositivo** ou edite um existente.
4. Preencha os campos:
   - **Nome do Dispositivo:** Ex: ESP32 Parque do Carmo (Será `urn:ngsi-ld:SensorDevice:XXX` se detectado automaticamente)
   - **ID Fiware:** Ex: `urn:ngsi-ld:SensorDevice:001` (Este deve ser o ID exato usado no Fiware)
   - **Latitude e Longitude:** Para geolocalização no mapa. Podem ser editados na página "Editar Localização".
   - **Descrição:** (opcional)
   - **Ativo:** Marque para ativar
5. Salve.

### 2. Via Django Shell (Exemplo)

Abra o shell:
```bash
python gs_fiap_monitor/manage.py shell
```
Cole e execute o seguinte código para criar/atualizar dispositivos de teste (ajuste os IDs conforme necessário):
```python
from sensores.models import Dispositivo

# Atualiza ou cria dispositivos de teste
Dispositivo.objects.update_or_create(
    id_dispositivo_fiware='urn:ngsi-ld:SensorDevice:001',
    defaults={
        'nome_dispositivo': 'ESP32 Teste 001',
        'localizacao_latitude': -23.5695,
        'localizacao_longitude': -46.4847,
        'descricao': 'Sensor de teste no Parque do Carmo',
        'ativo': True
    }
)
# Adicione mais dispositivos conforme necessário
```

## 🧪 Populando o Banco com Leituras Fictícias (Ambiente de Teste)

Para demonstrar o sistema com dados históricos, você pode criar leituras fictícias para os dispositivos cadastrados usando os comandos abaixo. Execute cada comando separadamente no terminal, dentro do diretório do projeto. Certifique-se de que os `id_dispositivo_fiware` correspondam aos dispositivos existentes no seu banco.

**Exemplo para um dispositivo com ID `urn:ngsi-ld:SensorDevice:001`:**

**Temperatura:**
```bash
python gs_fiap_monitor/manage.py shell -c "from sensores.models import Dispositivo, TipoSensor, LeituraSensor; from django.utils import timezone; from datetime import timedelta; device_id='urn:ngsi-ld:SensorDevice:001'; disp=Dispositivo.objects.get(id_dispositivo_fiware=device_id); tipo,_=TipoSensor.objects.get_or_create(nome='temperature',defaults={'unidade_medida':'CEL','descricao':'Sensor de temperatura'}); [LeituraSensor.objects.create(dispositivo=disp,tipo_sensor=tipo,valor=20+i,timestamp_leitura=timezone.now()-timedelta(hours=i)) for i in range(5)]"
```

**Umidade:**
```bash
python gs_fiap_monitor/manage.py shell -c "from sensores.models import Dispositivo, TipoSensor, LeituraSensor; from django.utils import timezone; from datetime import timedelta; device_id='urn:ngsi-ld:SensorDevice:001'; disp=Dispositivo.objects.get(id_dispositivo_fiware=device_id); tipo,_=TipoSensor.objects.get_or_create(nome='humidity',defaults={'unidade_medida':'P1','descricao':'Sensor de umidade'}); [LeituraSensor.objects.create(dispositivo=disp,tipo_sensor=tipo,valor=50+i*2,timestamp_leitura=timezone.now()-timedelta(hours=i)) for i in range(5)]"
```

**Nível de água:**
```bash
python gs_fiap_monitor/manage.py shell -c "from sensores.models import Dispositivo, TipoSensor, LeituraSensor; from django.utils import timezone; from datetime import timedelta; device_id='urn:ngsi-ld:SensorDevice:001'; disp=Dispositivo.objects.get(id_dispositivo_fiware=device_id); tipo,_=TipoSensor.objects.get_or_create(nome='waterLevel',defaults={'unidade_medida':'P1','descricao':'Sensor de nível de água'}); [LeituraSensor.objects.create(dispositivo=disp,tipo_sensor=tipo,valor=30+i*5,timestamp_leitura=timezone.now()-timedelta(hours=i)) for i in range(5)]"
```

Esses comandos criam 5 leituras para cada tipo de sensor para o dispositivo especificado, com timestamps retroativos, facilitando a visualização dos gráficos.
