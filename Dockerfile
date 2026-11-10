FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py .
COPY static/ static/

EXPOSE 8078

CMD ["python", "app.py"]
