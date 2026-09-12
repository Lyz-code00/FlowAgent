FROM python:3.12-slim

WORKDIR /app
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY pyproject.toml constraints.txt README.md* ./
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r constraints.txt \
    && pip install --no-cache-dir --index-url "$PIP_INDEX_URL" --no-deps .

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
