# CPU and Intel build of the Tier S AI worker. FFmpeg comes inside the PyAV wheel (LGPL build).
FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY worker ./worker
RUN useradd --system --uid 10002 hss
USER hss
CMD ["python", "-m", "worker.main"]
