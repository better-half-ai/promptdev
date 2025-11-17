#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=".env"

if [ -f "$ENV_FILE" ]; then
    echo "==> .env file already exists. Skipping."
    exit 0
fi

echo "==> Creating .env file with secure passwords..."

# Generate secure random passwords
PROMPTDEV_PASS=$(openssl rand -base64 32)
TEST_PASS=$(openssl rand -base64 32)

cat > "$ENV_FILE" << EOF
# Secrets ONLY — never DB hostnames, ports, users, or database names

POSTGRES_SUPERPASS=postgres
PROMPTDEV_USER_PASS=${PROMPTDEV_PASS}
PROMPTDEV_TEST_USER_PASS=${TEST_PASS}

# Optional future secrets (empty now)
PASETO_PRIVATE_KEY=
PASETO_PUBLIC_KEY=
EOF

# Secure the file
chmod 600 "$ENV_FILE"

echo "==> .env created with generated passwords"
echo "    File permissions: 600 (owner read/write only)"
echo ""
echo "IMPORTANT: Backup these credentials securely!"
echo "  PROMPTDEV_USER_PASS=${PROMPTDEV_PASS}"
echo "  PROMPTDEV_TEST_USER_PASS=${TEST_PASS}"
echo ""
