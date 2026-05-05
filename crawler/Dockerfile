FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY crawler.py .
COPY generate_articles.py .

CMD ["python", "crawler.py"]