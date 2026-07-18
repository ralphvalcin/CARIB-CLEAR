# CARIB-CLEAR Container Strategy
FROM python:3.11-slim AS base
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS runtime
COPY . .
EXPOSE 8000
ENV CARIB_CLEAR_ENV=production
CMD ["python", "-m", "carib_clear.api"]
