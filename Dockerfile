FROM mcr.microsoft.com/playwright/python:v1.60.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bms_monitor.py .

# Railway injects env vars at runtime via its dashboard -- no .env file needed in the image
CMD ["python3", "bms_monitor.py"]
