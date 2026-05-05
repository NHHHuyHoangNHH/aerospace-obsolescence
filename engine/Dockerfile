FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    google-cloud-bigquery \
    google-cloud-storage \
    google-cloud-bigquery-storage \
    xgboost \
    scikit-learn \
    sentence-transformers \
    pandas \
    numpy \
    pyarrow \
    db-dtypes \
    python-dotenv

COPY train.py .
COPY embeddings.py .
COPY retrain_pipeline.py .
ENTRYPOINT ["python3"]
CMD ["retrain_pipeline.py"]