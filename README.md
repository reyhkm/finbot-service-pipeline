# FinBot Financial Analytics Engine

Backend service for IDX stock market visualization with integrated Gemini Agentic Tool Calling.

## CI/CD Architecture
- Automated Testing: Pytest
- Security Analysis: Aqua Security Trivy
- Container Runtime: Docker (Non-root, dynamic port)
- Deployment Target: Ephemeral Verification & Google Cloud Run

## Local Execution
```bash
docker build -t finbot-service .
docker run -d -p 8080:8080 -e GEMINI_API_KEY="your-key" finbot-service
curl http://localhost:8080/
```
