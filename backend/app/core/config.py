from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "CrowdShield AI Backend"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    
    # Database
    DATABASE_URL: str
    APP_ENV: str = "development"
    
    # Security / Auth
    JWT_SECRET: str = "change-me-in-production-or-set-in-env"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days for dev

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
