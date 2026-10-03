FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data/samples ./data/samples
COPY data/raw ./data/raw
# No data/sessions directory: with S3_BUCKET / DDB_* set, sessions live in DynamoDB and S3,
# not on the (ephemeral, per-task) container disk.

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
