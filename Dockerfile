# NOT TESTED in this build. Only for a future server deployment (the POC runs locally without Docker).
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV BROWSER_CHANNEL=chromium
EXPOSE 8501 8000
CMD ["python", "-m", "src.main", "ui", "--server.address", "0.0.0.0"]
