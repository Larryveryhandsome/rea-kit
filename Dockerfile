FROM python:3.13-slim
WORKDIR /app
COPY requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt && useradd --uid 10001 --create-home app
COPY core/ ./core/
COPY adapters/ ./adapters/
COPY web/ ./web/
COPY docs/法遵/ ./docs/法遵/
COPY tools/serve_line.py tools/line_beta.py ./tools/
RUN mkdir /data && chown app:app /data
USER app
ENV REA_DATA_DIR=/data REA_BIND_HOST=0.0.0.0 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8080
CMD ["python", "tools/serve_line.py"]
