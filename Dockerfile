FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY app.py .

EXPOSE 8080

CMD ["streamlit", "run", "app.py", "--server.port=8080", "--server.enableCORS=false", "--server.enableXsrfProtection=false"]
