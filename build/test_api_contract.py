from pathlib import Path

source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
for expected in (
    '@api.get("/health")',
    '@api.get("/v1/models")',
    '@api.post("/v1/chat/completions")',
    'class ChatRequest(BaseModel)',
    'choices',
    'message',
    'content',
):
    assert expected in source, f"missing API contract element: {expected}"
print("API contract checks passed")
