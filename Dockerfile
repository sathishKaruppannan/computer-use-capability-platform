FROM mcr.microsoft.com/playwright/python:v1.51.0-noble
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .
CMD ["uvicorn", "capability_platform.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

