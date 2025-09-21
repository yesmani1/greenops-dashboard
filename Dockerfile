FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

# Cloud Run passes $PORT; default to 8080
CMD ["sh", "-c", "streamlit run app.py --server.port ${PORT:-8080} --server.address 0.0.0.0 --server.enableCORS=false --server.enableXsrfProtection=false"]
