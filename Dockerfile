FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

RUN useradd --create-home appuser || true
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY --chown=appuser:appuser app.py .

USER appuser
EXPOSE 8080

CMD ["streamlit", "run", "app.py", "--server.port=8080", "--server.enableCORS=false", "--server.enableXsrfProtection=false"]
