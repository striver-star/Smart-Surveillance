# Edge service: NVR event streams, device health and clips. FFmpeg (Debian package) runs as a
# separate program for clips only (stream copy, no re-encoding).
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY edge ./edge
RUN useradd --system --uid 10003 hss && mkdir -p /data && chown hss /data
USER hss
CMD ["python", "-m", "edge.main"]
