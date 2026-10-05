"""Root test configuration."""
import os

# Auth needs a signing secret; use a throwaway one for host runs (Docker passes the real .env).
os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)
