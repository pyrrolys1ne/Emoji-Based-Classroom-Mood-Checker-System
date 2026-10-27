FROM python:3.13-slim
WORKDIR /app
COPY services/ai/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/ai/app ./app
RUN useradd --create-home appuser
ENV AI_OUTBOX_PATH=/home/appuser/.local/ai-outbox.sqlite
USER appuser
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
