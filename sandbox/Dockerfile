# Build explicitly: docker build -t grid-sandbox:local sandbox
FROM python:3.12-slim
RUN pip install --no-cache-dir pytest==9.1.1
WORKDIR /workspace
USER 65534:65534
