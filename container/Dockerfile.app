FROM docker.io/library/python:3.12-slim
WORKDIR /app
RUN python3 -m venv /app/.slm-venv
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN /app/.slm-venv/bin/pip install --no-cache-dir --index-url ${TORCH_INDEX_URL} torch==2.11.0
RUN /app/.slm-venv/bin/pip install --no-cache-dir numpy scikit-learn==1.9.0 transformers==4.57.6
COPY requirements-research.txt ./
RUN /app/.slm-venv/bin/pip install --no-cache-dir -r requirements-research.txt
COPY *.py *.json ./
RUN mkdir -p /app/ctf_assets/source
COPY ctf_assets/ /app/ctf_assets/
RUN chown -R 1000:1000 /app/ctf_assets \
    && chmod 700 /app/ctf_assets /app/ctf_assets/source \
    && chmod 600 /app/ctf_assets/organizer-answer-key.json
COPY install.sh requirements*.txt compose.yaml compose.podman.yaml ./
COPY container/ ./container/
COPY web/ ./web/
COPY models-more/ ./models-more/
COPY models-specialists/ ./models-specialists/
COPY models-public/ ./models-public/
COPY models-domains/ ./models-domains/
COPY models-automotive/ ./models-automotive/
USER 1000:1000
ENV HOME=/tmp OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=4 LAB_CONTAINER=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["/app/.slm-venv/bin/python", "admin.py", "--container"]
