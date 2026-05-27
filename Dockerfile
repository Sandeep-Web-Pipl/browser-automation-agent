FROM python:3.11-slim
WORKDIR /app
COPY agent.py .
COPY dataset.json .
ENV INPUT_FILE=test_inputs.json
ENV OUTPUT_FILE=results.json
ENV DATASET_FILE=dataset.json
CMD ["python", "agent.py"]
