import os

APP_VERSION = "6.1.0"
APP_BUILD = "adaptive-feature-learning-v6-1"
APP_ENV = os.getenv("APP_ENV", "development").strip().lower() or "development"
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))
YOSOCAL_URL = "https://yosocal.com/"
YOSOCAL_CACHE_SECONDS = 60 * 60 * 6
OFFICIAL_CACHE_SECONDS = 60 * 60 * 3
