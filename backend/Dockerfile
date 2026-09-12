FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml constraints.txt README.md* ./
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --no-cache-dir -c constraints.txt .

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
