FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt && groupadd -r app && useradd -r -m -g app app
COPY . .
RUN mkdir -p /app/media && chown -R app:app /app && chmod +x /app/entrypoint.sh
USER app
EXPOSE 8000
CMD ["/app/entrypoint.sh"]
