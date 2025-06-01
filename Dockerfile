# Dockerfile for AVN Codex (formerly YAM)
# This file defines the Docker image for the Python Flask application.
# Python base image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Copy the dependencies file to the working directory
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# and Playwright browser dependencies
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

# Copy the content of the local src directory to the working directory
COPY . .

# Declare /data as a volume for persistent storage (e.g., database, logs)
VOLUME /data

# Environment variable to tell Playwright where to find browsers
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Specify the command to run on container start
CMD ["python", "app.py"] 