from __future__ import annotations

from app import app, db, ensure_account_lockout_schema


def main() -> None:
    with app.app_context():
        db.create_all()
        ensure_account_lockout_schema()


if __name__ == "__main__":
    main()
