FROM python:3.12-slim
WORKDIR /work
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# ECharts is embedded into the dashboard page (no CDN at runtime). Pinned by checksum.
ADD --chmod=644 --checksum=sha256:e84270bd0cd5bdf60fefc26d00c2a391cb2e81f4d26a7a9ee16185a54773a3cf \
    https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js /opt/echarts.min.js
ENV CNP_ECHARTS=/opt/echarts.min.js
