FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements-core.txt requirements-runtime.txt ./
RUN pip install --no-cache-dir -r requirements-runtime.txt \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home app
COPY --chown=app:app src ./src
COPY --chown=app:app scripts ./scripts
COPY --chown=app:app deploy ./deploy
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app data/processed ./data/processed
COPY --chown=app:app data/eval ./data/eval
RUN mkdir -p data/runtime/deployment data/uploads logs && chown -R app:app data logs
USER app
EXPOSE 8080
ENTRYPOINT ["python", "deploy/entrypoint.py"]
CMD ["api"]
