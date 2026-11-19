from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # LLM (opcional)
    LLM_ENABLED: bool = False
    LLM_PROVIDER: Optional[str] = None       # "openai" | "anthropic" | "groq"
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL: Optional[str] = None
    LLM_PROMPT: Optional[str] = (
        "Você é um assistente especialista em documentos financeiros brasileiros. "
        "Com base nos campos do boleto extraídos abaixo, faça uma análise objetiva."
    )

    # Servidor
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    LOG_LEVEL: str = "info"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
