FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV CONTAINER_ENV=true

EXPOSE 8080

# opentelemetry-instrument loads ADOT, which AgentCore Runtime configures through environment
# variables to send spans to AgentCore Observability (CloudWatch).
# 0.0.0.0 is inside the AgentCore microVM, which publishes no port: AgentCore's endpoint, with
# its Cognito authorizer, is the only way in.
CMD ["opentelemetry-instrument", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
