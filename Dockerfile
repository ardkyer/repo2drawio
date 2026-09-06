FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    REPO2DRAWIO_DATA_DIR=/data

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install --no-cache-dir .

# Mount /data explicitly with Docker Compose or the hosting provider's volume UI.
# Railway rejects the Dockerfile VOLUME instruction.
EXPOSE 8000
CMD ["repo2drawio-web"]
