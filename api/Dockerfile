FROM python:3.13-slim
WORKDIR /opt/api
COPY requirements-api.txt requirements-http.txt ./
RUN pip install --no-cache-dir -r requirements-api.txt
COPY app/ ./app/
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080
USER 65532:65532
CMD ["/bin/sh", "-c", "exec python -m uvicorn app.public_http:app_factory --factory --host 0.0.0.0 --port ${PORT:-8080} --no-access-log"]
