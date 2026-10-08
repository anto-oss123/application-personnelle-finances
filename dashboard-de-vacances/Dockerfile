FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY index.html server.py favicon.svg icon-192.png icon-512.png apple-touch-icon.png manifest.webmanifest ./
ENV HOST=0.0.0.0 PORT=8080
EXPOSE 8080
CMD ["python", "server.py"]
