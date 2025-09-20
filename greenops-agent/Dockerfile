FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

RUN useradd --create-home agentuser || true
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=agentuser:agentuser self_heal.py .

USER agentuser
CMD ["python", "self_heal.py"]
