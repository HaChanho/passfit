# 3.13-slim: dev venv(3.13)와 파리티. requirements-prod.lock = 런타임 전용 핀
FROM --platform=linux/amd64 python:3.13-slim
WORKDIR /app
COPY requirements-prod.lock pyproject.toml README.md ./
RUN pip install --no-cache-dir -r requirements-prod.lock
COPY src ./src
RUN pip install --no-cache-dir --no-deps .
ENV PORT=8080
EXPOSE 8080
CMD ["python", "-m", "passfit.server"]
