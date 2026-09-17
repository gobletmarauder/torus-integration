FROM python:3.12.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app
COPY src ./src

USER 65532:65532
CMD ["python", "-c", "import tis"]
