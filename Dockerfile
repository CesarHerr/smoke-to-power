FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Usuario sin privilegios para ejecutar la app
RUN useradd --create-home --uid 1000 appuser

WORKDIR /app

# server.py usa solo la librería estándar: no hace falta instalar dependencias
COPY server.py ./
COPY templates ./templates
COPY static ./static

USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/api/status', timeout=4).status == 200 else 1)"

CMD ["python3", "server.py"]
