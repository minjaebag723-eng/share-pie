# Share Pie 베타 서버 이미지 — docker-compose.yml이 이걸로 app 컨테이너를 만든다 (빌드 위치: 프로젝트 맨 위 폴더)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt deploy/requirements-server.txt ./
RUN pip install -r requirements.txt -r requirements-server.txt
COPY . .
# 데이터는 컨테이너 밖(호스트 폴더)에 둔다 — docker-compose.yml의 volumes
ENV DATA_DIR=/app/data BETA_DATA_DIR=/app/beta-data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"
# --workers 1 고정: 계정·방 상태를 한 프로세스 메모리에 두는 구조 (여러 개로 띄우면 데이터가 갈라짐)
CMD ["python", "-m", "uvicorn", "deploy.asgi:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--timeout-keep-alive", "30", "--proxy-headers", "--forwarded-allow-ips", "*"]
