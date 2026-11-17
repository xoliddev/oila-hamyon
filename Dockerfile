FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 TZ=Asia/Tashkent
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY hamyon ./hamyon
# Root huquqisiz ishlaydi; /app/data ga yozish uchun shu foydalanuvchi egasi bo'ladi
RUN useradd --create-home --uid 10001 hamyon && mkdir -p /app/data && chown hamyon /app/data
USER hamyon
VOLUME ["/app/data"]

CMD ["python", "-m", "hamyon"]
