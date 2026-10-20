FROM python:3.12-slim

LABEL org.opencontainers.image.title="DMbuddy Connector" \
      org.opencontainers.image.description="Outbound Connector for private printer networks" \
      org.opencontainers.image.source="https://github.com/quocanhcgd/DMBuddy"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PRINTBUDDY_CONNECTOR_STATE=/var/lib/printbuddy-connector/state.json

WORKDIR /app
COPY connector/requirements.txt ./connector/requirements.txt
RUN python -m pip install --no-cache-dir --upgrade "pip>=26.1" \
    && python -m pip install --no-cache-dir -r connector/requirements.txt
COPY connector_protocol/ ./connector_protocol/
COPY connector/ ./connector/
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin printbuddy \
    && mkdir -p /var/lib/printbuddy-connector \
    && chown -R printbuddy:printbuddy /app /var/lib/printbuddy-connector
USER printbuddy
VOLUME ["/var/lib/printbuddy-connector"]
ENTRYPOINT ["python", "-m", "connector.printbuddy_connector"]
