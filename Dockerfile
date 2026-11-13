FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 TZ=Asia/Tashkent
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY hamyon ./hamyon
VOLUME ["/app/data"]

CMD ["python", "-m", "hamyon"]
