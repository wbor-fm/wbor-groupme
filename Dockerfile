# Use a specific, smaller Python image as a base
FROM python:3.10-slim

# Set environment variables and define working directory
ENV PYTHONUNBUFFERED=1
ENV PYTHONHASHSEED=0
WORKDIR /app

# Install necessary system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libssl-dev libffi-dev libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy only the requirements file and install dependencies first
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Expose the Flask app port
EXPOSE 2000

# Keep --workers at 1 unless decoupling RabbitMQ consumption from Gunicorn workers
CMD ["gunicorn", "--workers", "1", "--bind", "0.0.0.0:2000", "app:app", "-c", "gunicorn_config.py"]