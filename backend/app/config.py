"""Central settings. Everything can be overridden with environment variables."""
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("FEEDBACK_DATA_DIR", ROOT / "data"))
DB_PATH = Path(os.getenv("FEEDBACK_DB", DATA_DIR / "feedback.db"))

# k-anonymity style floor: no report is produced for a group smaller than this.
MIN_GROUP_SIZE = int(os.getenv("MIN_GROUP_SIZE", "5"))

# Comments shorter than this (in words) carry no usable signal and are skipped.
MIN_COMMENT_WORDS = int(os.getenv("MIN_COMMENT_WORDS", "3"))


def get_salt() -> bytes:
    """Secret used to hash respondent ids.

    Production: set FEEDBACK_SALT in the environment (never commit it).
    Development: a random salt is generated once and kept in data/.salt.
    The salt is never stored in the database, so the hashes cannot be reversed
    or re-derived by someone who only has the DB file.
    """
    env = os.getenv("FEEDBACK_SALT")
    if env:
        return env.encode()
    salt_file = DATA_DIR / ".salt"
    if not salt_file.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        salt_file.write_text(secrets.token_hex(32))
        try:
            salt_file.chmod(0o600)
        except OSError:
            pass
    return salt_file.read_text().strip().encode()
