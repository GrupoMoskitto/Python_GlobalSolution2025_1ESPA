from django.db import models
from django.utils import timezone

class Dispositivo(models.Model):
    nome_dispositivo = models.CharField(max_length=100, unique=True)
    id_dispositivo_fiware = models.CharField(max_length=100, unique=True, help_text="ID único do dispositivo no Fiware Orion")
    localizacao_latitude = models.FloatField(null=True, blank=True)
    localizacao_longitude = models.FloatField(null=True, blank=True)
    descricao = models.TextField(blank=True)
    data_criacao = models.DateTimeField(default=timezone.now)
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return str(self.nome_dispositivo)

class TipoSensor(models.Model):
    nome = models.CharField(max_length=50, unique=True, help_text="Ex: UmidadeSolo, TemperaturaAr, waterLevel")
    unidade_medida = models.CharField(max_length=20, help_text="Ex: %, °C, cm")
    descricao = models.TextField(blank=True)

    def __str__(self):
        return f"{self.nome} ({self.unidade_medida})"

class LeituraSensor(models.Model):
    dispositivo = models.ForeignKey(Dispositivo, on_delete=models.CASCADE, related_name='leituras')
    tipo_sensor = models.ForeignKey(TipoSensor, on_delete=models.PROTECT, related_name='leituras') # PROTECT para não apagar o tipo se houver leituras
    valor = models.FloatField()
    timestamp_leitura = models.DateTimeField(help_text="Timestamp da leitura original no dispositivo")
    timestamp_recebimento = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.dispositivo.nome_dispositivo} - {self.tipo_sensor.nome}: {self.valor} {self.tipo_sensor.unidade_medida} @ {self.timestamp_leitura}"

    class Meta:
        ordering = ['-timestamp_leitura']
