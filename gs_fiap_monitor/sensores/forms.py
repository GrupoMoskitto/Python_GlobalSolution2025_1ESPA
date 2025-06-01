from django import forms
from .models import Dispositivo

class DispositivoLocalizacaoForm(forms.ModelForm):
    class Meta:
        model = Dispositivo
        fields = ['localizacao_latitude', 'localizacao_longitude']
        widgets = {
            'localizacao_latitude': forms.NumberInput(attrs={'class': 'w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent', 'placeholder': 'Ex: -23.550520'}),
            'localizacao_longitude': forms.NumberInput(attrs={'class': 'w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent', 'placeholder': 'Ex: -46.633308'}),
        }
        labels = {
            'localizacao_latitude': 'Latitude',
            'localizacao_longitude': 'Longitude',
        }
        help_texts = {
            'localizacao_latitude': 'Coordenada de latitude do dispositivo.',
            'localizacao_longitude': 'Coordenada de longitude do dispositivo.',
        }

    def clean(self):
        cleaned_data = super().clean()
        latitude = cleaned_data.get("localizacao_latitude")
        longitude = cleaned_data.get("localizacao_longitude")

        if latitude is not None and (latitude < -90 or latitude > 90):
            self.add_error('localizacao_latitude', "Latitude deve estar entre -90 e 90.")
        
        if longitude is not None and (longitude < -180 or longitude > 180):
            self.add_error('localizacao_longitude', "Longitude deve estar entre -180 e 180.")
            
        return cleaned_data 