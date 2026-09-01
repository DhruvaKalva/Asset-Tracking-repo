FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first so code edits do not bust the wheel cache.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# The API is stateless: scale with replicas, not with more workers per box.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
