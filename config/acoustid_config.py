import os

ACOUSTID_API_KEY = os.getenv('ACOUSTID_API')
CACHE_DB_PATH = "../music_collection.db"
ALBUM_ART_DIR = "../album_art"

# Recognition settings
RECOGNITION_BUFFER_SECONDS = 10
CONFIDENCE_THRESHOLD = 0.5
ALLOW_ONLINE_FALLBACK = False
