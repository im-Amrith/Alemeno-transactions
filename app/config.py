from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres@db:5432/txnpipeline"
    redis_url: str = "redis://redis:6379/0"
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    upload_dir: str = "/data/uploads"
    classification_batch_size: int = 18
    llm_max_retries: int = 3

    class Config:
        env_file = ".env"


settings = Settings()
