FROM python:3.12-slim

WORKDIR /app
COPY dmm.py .

RUN mkdir -p /app/data

ENV PYTHONUNBUFFERED=1
CMD ["python", "dmm.py", "loop"]
