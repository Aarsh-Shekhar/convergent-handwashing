# Backend-only image (no MediaPipe/PyTorch): used by docker-compose for the persistent backend.
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY configs ./configs
RUN pip install --no-cache-dir "fastapi>=0.115,<0.116" "uvicorn[standard]>=0.32,<0.35" "sqlalchemy>=2.0.36,<2.1" \
    "alembic>=1.14,<2" "psycopg[binary]>=3.2,<4" "pydantic>=2.9,<3" "pydantic-settings>=2.6,<3" "pyyaml>=6" \
    "python-dotenv>=1" "httpx>=0.27" "numpy>=1.26,<2" "websockets>=13.1,<15" "psutil>=6" "scipy>=1.13,<1.16" \
    "opencv-python-headless>=4.10,<4.12" "scikit-learn>=1.5,<1.7" "pillow>=10.4,<12" && pip install --no-cache-dir -e . --no-deps
EXPOSE 8000
CMD ["python", "-m", "convergent.cli", "backend", "--host", "0.0.0.0"]
