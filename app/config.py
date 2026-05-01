import os

from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-schimba-in-productie")
ALGORITHM = os.environ.get("ALGORITHM", "HS256")
EXPIRARE_TOKEN_MINUTE = int(os.environ.get("EXPIRARE_TOKEN_MINUTE", "60"))
DATABASE_PATH = os.environ.get("DATABASE_PATH", "sarcini.db")
