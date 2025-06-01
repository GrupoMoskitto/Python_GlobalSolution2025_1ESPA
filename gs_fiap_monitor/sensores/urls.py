from django.urls import path
from . import views

app_name = 'sensores'

urlpatterns = [
    path('fiware_notification/', views.fiware_notification_receiver, name='fiware_notification_receiver'),
    path('dispositivos/', views.listar_dispositivos, name='listar_dispositivos'),
    path('mapa/', views.mapa_interativo_view, name='mapa_interativo'),
    path('dispositivo/<str:id_dispositivo_fiware>/', views.detalhes_dispositivo, name='detalhes_dispositivo'),
    path('dispositivo/<str:id_dispositivo_fiware>/editar-localizacao/', views.editar_localizacao_dispositivo, name='editar_localizacao_dispositivo'),
    path('detectar-novos-dispositivos/', views.detectar_novos_dispositivos_fiware, name='detectar_novos_dispositivos'),
] 