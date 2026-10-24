# The web console (domestique.web). Built from the repository; contains no
# athlete data. Configuration is mounted read-only at /config, secrets come
# from the container's environment. See docker-compose.yml, service "app".
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DOMESTIQUE_MIGRATIONS=/app/migrations

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY migrations ./migrations
RUN pip install --no-cache-dir . && rm -rf src

EXPOSE 8000
CMD ["python", "-m", "domestique.web"]
