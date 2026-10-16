from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    db_name: str = "inventory_sales"
    test_db_name: str = "inventory_sales_test"
    jwt_secret: str = "development-only-change-this-secret"
    jwt_expires_minutes: int = 60


settings = Settings()
