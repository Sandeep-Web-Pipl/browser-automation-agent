FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent.py .
COPY dataset.json .

ENV INPUT_FILE=test_inputs.json
ENV OUTPUT_FILE=results.json
ENV DATASET_FILE=dataset.json

CMD ["python", "agent.py"]
