FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin appuser
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY app.py /app/app.py
RUN chown -R appuser:appuser /app
USER 10001:10001
EXPOSE 8080
CMD ["uvicorn","app:APP","--host","0.0.0.0","--port","8080","--workers","1","--proxy-headers"]
