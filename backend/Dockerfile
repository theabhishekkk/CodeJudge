FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -e .
EXPOSE 8000
CMD ["uvicorn", "codejudge.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
