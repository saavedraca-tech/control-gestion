# API (FastAPI) + motor de cierre. Se construye desde la raíz porque usa src/, cierre.py y plantillas_rubro/.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./requirements.txt
COPY web/backend/requirements.txt ./web/backend/requirements.txt
RUN pip install --no-cache-dir -r web/backend/requirements.txt
COPY src ./src
COPY plantillas_rubro ./plantillas_rubro
COPY cierre.py nuevo_cliente.py ./
COPY web/backend/app ./web/backend/app
WORKDIR /app/web/backend
RUN useradd -m app && chown -R app /app
USER app
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
