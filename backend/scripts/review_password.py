"""Хэш пароля для входа ревьюеров: значение секрета REVIEW_PASSWORD_HASH.

    python scripts/review_password.py            # спросит пароль
    python scripts/review_password.py --generate # придумает пароль и напечатает его вместе с хэшем
"""

import argparse
import getpass
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.review_login import make_hash  # noqa: E402

ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true", help="Придумать пароль из 16 символов")
    args = parser.parse_args()
    if args.generate:
        password = "".join(secrets.choice(ALPHABET) for _ in range(16))
        print(f"password: {password}")
    else:
        password = getpass.getpass("Пароль: ")
        if len(password) < 12:
            raise SystemExit("Пароль не короче 12 символов")
    print(f"REVIEW_PASSWORD_HASH={make_hash(password)}")


if __name__ == "__main__":
    main()
