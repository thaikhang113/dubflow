FROM python:3.11-slim@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models \
    VIENEU_MODELS_DIR=/models

RUN apt-get update \
    && apt-get install -y --no-install-recommends libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt
ARG VIENEU_TORCH_INDEX=""
RUN if [ -n "$VIENEU_TORCH_INDEX" ]; then \
      pip install --no-cache-dir --index-url "$VIENEU_TORCH_INDEX" \
        torch==2.6.0 torchaudio==2.6.0 \
      && pip install --no-cache-dir transformers==4.57.1; \
    fi
COPY app.py .

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
