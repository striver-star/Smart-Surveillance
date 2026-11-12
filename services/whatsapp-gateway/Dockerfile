FROM node:22.12.0-bookworm-slim
# Chromium from Debian (BSD-style licence); puppeteer must not download its own copy.
RUN apt-get update && apt-get install -y --no-install-recommends chromium fonts-liberation ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ENV PUPPETEER_SKIP_DOWNLOAD=true CHROMIUM_PATH=/usr/bin/chromium HSS_WA_DATA=/data NODE_ENV=production
WORKDIR /srv
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY server.js ./
RUN mkdir -p /data && chown node:node /data
USER node
EXPOSE 3000
CMD ["node", "server.js"]
