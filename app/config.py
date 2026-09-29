import os


DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://issuelens:issuelens@localhost:5433/issuelens"
)
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen3:4b"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 30.0


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def get_github_token() -> str | None:
    return os.getenv("GITHUB_TOKEN") or None


def get_ollama_base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).rstrip("/")


def get_ollama_model() -> str:
    return os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)


def get_ollama_timeout_seconds() -> float:
    value = float(
        os.getenv("OLLAMA_TIMEOUT_SECONDS", str(DEFAULT_OLLAMA_TIMEOUT_SECONDS))
    )
    if value <= 0:
        raise ValueError("OLLAMA_TIMEOUT_SECONDS must be greater than zero")
    return value
