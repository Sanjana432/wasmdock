FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN python -m pip install --no-cache-dir -e . && useradd --create-home appuser && mkdir -p .data && chown -R appuser:appuser /app
USER appuser
EXPOSE 8020
CMD ["python", "-m", "uvicorn", "wasmdock.app:app", "--host", "0.0.0.0", "--port", "8020"]
