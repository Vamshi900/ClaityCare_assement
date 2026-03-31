from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://oscar:oscar_dev_pw@localhost:5432/oscar_guidelines"
    storage_dir: str = "/root/oscar-guidelines/storage"
    llm_provider: str = "anthropic"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    llm_model_anthropic: str = "claude-sonnet-4-6"
    llm_model_openai: str = "gpt-4o"
    oscar_source_url: str = "https://www.hioscar.com/clinical-guidelines/medical"

    class Config:
        env_file = "../.env"

settings = Settings()
