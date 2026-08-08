FROM python:3.11-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TOOL_ROOT=/data \
    TOOL_BIND_HOST=0.0.0.0 \
    TOOL_BIND_PORT=18793 \
    HOME=/home/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    build-essential \
    ca-certificates \
    chromium \
    cmake \
    curl \
    ffmpeg \
    fonts-noto-cjk \
    git \
    gosu \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libsndfile1 \
    procps \
    tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-web.txt /app/requirements-web.txt
RUN pip install --no-cache-dir -r requirements-web.txt \
    && pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        torch==2.2.2+cpu \
    && pip install --no-cache-dir \
        Pillow \
        Pyro4 \
        demucs==4.1.0 \
        fonttools \
        matplotlib \
        numpy==1.26.4 \
        onnxruntime==1.18.1 \
        paddleocr==2.7.3 \
        paddlepaddle==2.6.2 \
        pandas \
        pyannote.core==5.0.0 \
        pytextgrid \
        scikit-image \
        soundfile \
        tensorflow-cpu==2.16.2 \
    && pip install --no-cache-dir --no-deps inaSpeechSegmenter==0.7.12

RUN git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git /opt/whisper.cpp \
    && cmake -S /opt/whisper.cpp -B /opt/whisper.cpp/build \
    && cmake --build /opt/whisper.cpp/build --config Release --target whisper-cli -j2

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data/data /data/secrets /data/jobs /data/output /data/models /data/browser \
    && chown -R app:app /data /home/app

COPY . /app
RUN find /app/skills /app/docker -type f -name '*.sh' -exec sed -i 's/\r$//' {} + \
    && chmod +x /app/docker/entrypoint.sh

EXPOSE 18793
ENTRYPOINT ["/app/docker/entrypoint.sh"]
