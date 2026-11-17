FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY . .
# One worker on purpose: rooms are locked per process, so run a single process per database.
ENV PORT=5000 PYTHONUNBUFFERED=1
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:5000/api/ping')"
CMD ["sh", "-c", "gunicorn -w 1 --threads 16 -b 0.0.0.0:${PORT} app:app"]
