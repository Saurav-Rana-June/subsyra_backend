from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DB_CONNECTION: str
    SECRET_KEY: str
    ALGORITHM: str
    TOKEN_EXP_TIME: int

    # Razorpay Test Credentials:
    RAZORPAY_KEY_ID: str
    RAZORPAY_KEY_SECRET: str
    RAZORPAY_WEBHOOK_SECRET: str

    # Redis Cache Configuration:
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_ENABLED: bool = True


settings = Settings()
