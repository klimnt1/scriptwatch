#!/bin/sh
set -eu

if [ -f .env ]; then
  echo ".env already exists; leaving it unchanged."
  exit 0
fi

secret() {
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
}

cp .env.example .env
sed -i "s|AGENT_TOKEN=generate_a_long_random_string_here|AGENT_TOKEN=$(secret)|" .env
sed -i "s|SECRET_KEY=generate_a_long_random_string_here|SECRET_KEY=$(secret)|" .env
echo "Created .env with fresh AGENT_TOKEN and SECRET_KEY."
