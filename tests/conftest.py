import os

# Chạy trước khi import app: biến môi trường thắng giá trị trong .env, nên test
# không gọi Gemini/Ollama thật và không ghi vào egress log của máy demo.
os.environ["AI_MODE"] = "mock"
os.environ["EGRESS_LOG_ENABLED"] = "false"
