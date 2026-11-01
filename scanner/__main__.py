import uvicorn

from scanner.config import Settings

if __name__ == "__main__":
    settings = Settings.from_env()
    uvicorn.run("scanner.api:app", host=settings.host, port=settings.port, workers=1)
