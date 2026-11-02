FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN adduser --disabled-password --gecos '' appuser && mkdir -p /data && chown appuser:appuser /data
USER appuser
EXPOSE 10000
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--workers", "1", "--threads", "8", "--timeout", "600", "app:app"]

