from django.urls import path
from . import views

app_name = 'sensores'

urlpatterns = [
    path('', views.hub_sensores_view, name='hub_sensores'),
    path('fiware_notification/', views.fiware_notification_receiver, name='fiware_notification_receiver'),
    path('dispositivos/', views.listar_dispositivos, name='listar_dispositivos'),
    path('mapa/', views.mapa_interativo, name='mapa_interativo'),
    path('dispositivo/<path:id_dispositivo_fiware>/editar-localizacao/', views.editar_localizacao_dispositivo, name='editar_localizacao_dispositivo'),
    path('dispositivo/<path:id_dispositivo_fiware>/', views.detalhes_dispositivo, name='detalhes_dispositivo'),
    path('api/dispositivo/<path:id_dispositivo_fiware>/dados/', views.dados_dispositivo_json, name='dados_dispositivo_json'),
    path('api/dispositivos/status/', views.api_listar_dispositivos_status, name='api_listar_dispositivos_status'),
    path('api/mapa/dispositivos/', views.api_mapa_dispositivos_status, name='api_mapa_dispositivos_status'),
    path('detectar-novos-dispositivos/', views.detectar_novos_dispositivos_fiware, name='detectar_novos_dispositivos'),
] 