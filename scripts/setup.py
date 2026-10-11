#!/usr/bin/env python3
"""Create local configuration. Never overwrite an existing .env."""

import secrets
from pathlib import Path

root = Path(__file__).resolve().parent.parent
path = root / ".env"
if path.exists():
    raise SystemExit(".env already exists; keeping existing configuration.")
text = (root / ".env.example").read_text()
password = secrets.token_urlsafe(18)
for key, value in {
    "DJANGO_SECRET_KEY": secrets.token_urlsafe(48),
    "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
    "ADMIN_PASSWORD": password,
}.items():
    text = text.replace(f"{key}=\n", f"{key}={value}\n")
path.write_text(text)
path.chmod(0o600)
print("Created .env. Keep it private and back it up separately.")
print("Login: admin")
print("Initial password:", password)
print("Run: docker compose up -d --build")
