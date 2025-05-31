from django.urls import path
from . import views

app_name = 'sensores'

urlpatterns = [
    path('fiware_notification/', views.fiware_notification_receiver, name='fiware_notification_receiver'),
    path('dispositivos/', views.listar_dispositivos, name='listar_dispositivos'),
    path('mapa/', views.mapa_interativo_view, name='mapa_interativo'),
    path('dispositivo/<str:id_dispositivo_fiware>/', views.detalhes_dispositivo, name='detalhes_dispositivo'),
] 