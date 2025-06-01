from django import template
from django.utils import timezone
import pytz

register = template.Library()

@register.filter(name='to_brasilia_time')
def to_brasilia_time(utc_datetime):
    print(f"[to_brasilia_time DEBUG] Recebido: {utc_datetime}, Tipo: {type(utc_datetime)}")
    if not utc_datetime:
        print("[to_brasilia_time DEBUG] Retornando vazio (input nulo/vazio).")
        return ""
    
    original_value_for_debug = utc_datetime # Guardar o valor original para o log de retorno

    if not timezone.is_aware(utc_datetime):
        print(f"[to_brasilia_time DEBUG] Input é naive. Tornando aware com UTC: {utc_datetime}")
        # Se for um datetime naive, assume que é UTC
        utc_datetime = timezone.make_aware(utc_datetime, timezone.utc)
        print(f"[to_brasilia_time DEBUG] Agora aware: {utc_datetime}")
    
    brasilia_tz = pytz.timezone('America/Sao_Paulo') # GMT-3, considera horário de verão se aplicável
    try:
        local_time = utc_datetime.astimezone(brasilia_tz)
        print(f"[to_brasilia_time DEBUG] Convertido para America/Sao_Paulo: {local_time}")
        return local_time
    except Exception as e:
        print(f"[to_brasilia_time DEBUG] Erro ao converter fuso horário para {original_value_for_debug}: {e}")
        return original_value_for_debug # Retorna o original em caso de erro na conversão 