# Stage 1: Build frontend
FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ .
RUN npm run build

# Stage 2: Python runtime
FROM python:3.13-slim
WORKDIR /app

# Install Python dependencies
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .

# Copy built frontend from stage 1
COPY --from=frontend-build /app/frontend/dist frontend/dist

# Copy config
COPY config.yaml .

# Data directory for SQLite
RUN mkdir -p /app/data
ENV DB_PATH=/app/data/trading_bot.db

EXPOSE 8000

CMD ["trading-bot", "serve", "--host", "0.0.0.0"]
