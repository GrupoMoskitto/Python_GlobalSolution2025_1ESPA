from django.contrib import admin
from .models import Dispositivo, TipoSensor, LeituraSensor

# Register your models here.
admin.site.register(Dispositivo)
admin.site.register(TipoSensor)
admin.site.register(LeituraSensor)
