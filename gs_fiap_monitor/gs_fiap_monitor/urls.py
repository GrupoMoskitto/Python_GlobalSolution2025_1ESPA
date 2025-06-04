"""
URL configuration for gs_fiap_monitor project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from sensores import views as sensores_views
# Os imports abaixo (settings e static) podem não ser mais necessários 
# se não forem usados em nenhum outro lugar após a remoção do bloco if not settings.DEBUG
# from django.conf import settings
# from django.conf.urls.static import static # Removido pois static() não é mais usado aqui

urlpatterns = [
    path('admin/', admin.site.urls),
    path('sensores/', include('sensores.urls', namespace='sensores_api')),
    path('', sensores_views.home_page, name='home_page'),
]

handler404 = 'gs_fiap_monitor.views.custom_page_not_found_view'

# O bloco if not settings.DEBUG foi removido pois WhiteNoise cuidará de servir estáticos.
