<p align="center">
  <img src="https://img.shields.io/badge/Django-5.2.1-green?logo=django" alt="Django"/>
  <img src="https://img.shields.io/badge/REST%20API-DRF-blue?logo=django" alt="REST"/>
  <img src="https://img.shields.io/badge/Plotly-Graphs-orange?logo=plotly" alt="Plotly"/>
</p>

<h1 align="center">🌱 GS FIAP Monitor</h1>

> **Sistema web para monitoramento de sensores (umidade, temperatura, nível de água) integrados via ESP32 e Fiware Orion Context Broker. Visual moderno, responsivo e com gráficos interativos.**

---

## 🚀 Funcionalidades

| Funcionalidade                        | Descrição                                                                 |
|---------------------------------------|--------------------------------------------------------------------------|
| 📡 Integração Fiware                  | Recebe dados de sensores via Orion Context Broker                        |
| 📋 Listagem de Dispositivos           | Cards com status colorido, últimas leituras e link para detalhes         |
| 📈 Gráficos Interativos               | Histórico de leituras com Plotly                                         |
| 🗺️ Mapa Interativo                    | Localização dos dispositivos, legendas e filtros                         |
| 🔒 Administração                      | Gerenciamento fácil via Django Admin                                     |
| 🎨 Visual Moderno                     | TailwindCSS, responsivo, navegação fluida                                |

---


## 📦 Modelos de Dados

| Modelo           | Campos Principais                                                                                 |
|------------------|--------------------------------------------------------------------------------------------------|
| **Dispositivo**  | nome_dispositivo, id_dispositivo_fiware, latitude, longitude, descricao, data_criacao, ativo      |
| **TipoSensor**   | nome, unidade_medida, descricao                                                                  |
| **LeituraSensor**| dispositivo (FK), tipo_sensor (FK), valor, timestamp_leitura, timestamp_recebimento              |

### Exemplo de Dados

```json
{
  "dispositivo": "esp32_01",
  "tipo_sensor": "temperature",
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
| Folium/Leaflet     | 0.19.6    | Mapas interativos                         |
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
   - Sistema: [http://localhost:8000/](http://localhost:8000/)
   - Admin: [http://localhost:8000/admin/](http://localhost:8000/admin/)

---

## 🔗 Integração com Fiware

- O endpoint `/api/fiware/notify/` recebe notificações NGSI do Orion Context Broker e armazena as leituras automaticamente.

### Exemplo de Payload Aceito

```json
{
  "data": [
    {
      "id": "esp32_01",
      "type": "SensorDevice",
      "temperature": {"value": 23.5, "type": "Number"},
      "humidity": {"value": 60, "type": "Number"},
      "waterLevel": {"value": 45, "type": "Number"},
      "timestamp": {"value": "2024-06-10T12:00:00Z"}
    }
  ]
}
```

---

## 📊 Visualização

| Página                  | Descrição                                                                 |
|-------------------------|--------------------------------------------------------------------------|
| **Listagem**            | Cards de dispositivos, status colorido, últimas leituras                  |
| **Detalhes**            | Gráficos interativos (Plotly), status calculado, informações completas    |
| **Mapa**                | Dispositivos geolocalizados, legendas, filtros                           |
| **Admin**               | Gerenciamento de dispositivos, sensores e leituras                        |

---

## 🧑‍💻 Contribuição

1. Faça um fork do projeto
2. Crie uma branch (`git checkout -b feature/sua-feature`)
3. Commit suas alterações (`git commit -am 'feat: nova feature'`)
4. Push para o branch (`git push origin feature/sua-feature`)
5. Abra um Pull Request

## 🛰️ Como Adicionar e Configurar Dispositivos ESP32

Você pode cadastrar e configurar dispositivos ESP32 (sensores) de duas formas:

### 1. Via Django Admin

1. Acesse o painel de administração: `http://localhost:8000/admin/`
2. Clique em **Dispositivos**.
3. Clique em **Adicionar Dispositivo** ou edite um existente.
4. Preencha os campos:
   - **Nome do Dispositivo:** Ex: ESP32 Parque do Carmo
   - **ID Fiware:** Ex: esp32_parque_carmo
   - **Latitude:** Ex: `-23.5695` (Parque do Carmo)
   - **Longitude:** Ex: `-46.4847` (Parque do Carmo)
   - **Descrição:** (opcional)
   - **Ativo:** Marque para ativar
5. Salve.

Exemplos de coordenadas:
- **Parque do Carmo:** Latitude `-23.5695`, Longitude `-46.4847`
- **Pinheiros:** Latitude `-23.5614`, Longitude `-46.6794`
- **Morumbi:** Latitude `-23.6010`, Longitude `-46.7156`

### 2. Via Django Shell

Abra o shell:
```bash
python gs_fiap_monitor/manage.py shell
```
Cole e execute o seguinte código para criar/atualizar dispositivos de teste:
```python
from sensores.models import Dispositivo

# Atualiza ou cria dispositivos de teste
Dispositivo.objects.update_or_create(
    id_dispositivo_fiware='esp32_parque_carmo',
    defaults={
        'nome_dispositivo': 'ESP32 Parque do Carmo',
        'localizacao_latitude': -23.5695,
        'localizacao_longitude': -46.4847,
        'descricao': 'Sensor próximo ao Parque do Carmo',
        'ativo': True
    }
)
Dispositivo.objects.update_or_create(
    id_dispositivo_fiware='esp32_pinheiros',
    defaults={
        'nome_dispositivo': 'ESP32 Pinheiros',
        'localizacao_latitude': -23.5614,
        'localizacao_longitude': -46.6794,
        'descricao': 'Sensor no bairro de Pinheiros',
        'ativo': True
    }
)
Dispositivo.objects.update_or_create(
    id_dispositivo_fiware='esp32_morumbi',
    defaults={
        'nome_dispositivo': 'ESP32 Morumbi',
        'localizacao_latitude': -23.6010,
        'localizacao_longitude': -46.7156,
        'descricao': 'Sensor no bairro do Morumbi',
        'ativo': True
    }
)
```

Depois, envie dados para esses dispositivos normalmente pelo endpoint Fiware.
