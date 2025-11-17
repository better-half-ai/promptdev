FROM python:3.11-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Install project deps
COPY pyproject.toml .
RUN uv pip install --system .

# Copy source
COPY src ./src

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8001"]