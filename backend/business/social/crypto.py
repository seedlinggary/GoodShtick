import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from config import application


def _fernet():
    """Derives a stable 32-byte urlsafe-base64 Fernet key from the app's own
    SECRET_KEY so social OAuth tokens are encrypted at rest without needing a
    separate key to provision/rotate/leak."""
    digest = hashlib.sha256(application.config['SECRET_KEY'].encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_token(raw):
    if not raw:
        return None
    return _fernet().encrypt(raw.encode('utf-8')).decode('utf-8')


def decrypt_token(enc):
    if not enc:
        return None
    try:
        return _fernet().decrypt(enc.encode('utf-8')).decode('utf-8')
    except InvalidToken:
        return None
