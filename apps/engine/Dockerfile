# ⚠️ Image API/lecture seule. Depuis la migration MetaTrader 5, le moteur de
# TRADING ne peut PAS tourner dans ce conteneur : le paquet Python MetaTrader5
# est Windows-only et exige un terminal MT5 local. Cette image ne sert que si
# l'on veut exposer les endpoints DB (candles/decisions) sans broker.
# Le moteur complet se lance nativement sous Windows (voir start.ps1).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
# Le marqueur sys_platform exclut MetaTrader5 sous Linux : l'install passe,
# mais tout endpoint broker répondra 503.
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
