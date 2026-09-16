FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/src

RUN apt-get update && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir \
      pydantic pydantic-settings pyyaml httpx python-dotenv typer rich tenacity \
      gspread google-auth google-api-python-client

COPY src/ ./src/
COPY config/ ./config/
COPY prompts/ ./prompts/

EXPOSE 8000
ENTRYPOINT ["python", "-m", "ci"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
