"""Zero-trust document vault.

Envelope encryption: every file gets its own random 256-bit data key (DEK) and is sealed
with AES-256-GCM. The DEK is itself wrapped by a versioned master key (KEK). Rotating the
KEK only re-wraps DEKs — file ciphertext never has to be rewritten. The storage backend is
a local directory here; an S3/GCS backend with CMEK implements the same three methods.
"""
import base64
import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import settings

_STORE = Path(settings.STORAGE_DIR)
_STORE.mkdir(parents=True, exist_ok=True)
_KEY_FILE = _STORE / ".dev_keks"


def _load_keks() -> dict[str, bytes]:
    raw = settings.VAULT_KEKS.strip()
    if not raw:
        # Dev convenience: persist a generated key next to storage. Production must set VAULT_KEKS.
        if not _KEY_FILE.exists():
            _KEY_FILE.write_text("v1:" + base64.b64encode(os.urandom(32)).decode())
        raw = _KEY_FILE.read_text().strip()
    keks = {}
    for i, part in enumerate(raw.split(",")):
        ver, b64 = part.split(":", 1) if ":" in part else (f"v{i + 1}", part)
        key = base64.b64decode(b64.strip() + "=" * (-len(b64.strip()) % 4))
        if len(key) != 32:  # accept any secret (e.g. Render generateValue) — derive a 256-bit key
            key = hashlib.sha256(key).digest()
        keks[ver.strip()] = key
    return keks


_KEKS = _load_keks()


def active_kek_version() -> str:
    return list(_KEKS.keys())[-1]


def kek_versions() -> list[str]:
    return list(_KEKS.keys())


def add_kek(version: str) -> None:
    """Generate a new KEK (used by the DevSecOps agent's rotation routine)."""
    _KEKS[version] = os.urandom(32)
    if not settings.VAULT_KEKS.strip():
        _KEY_FILE.write_text(",".join(f"{v}:{base64.b64encode(k).decode()}" for v, k in _KEKS.items()))


def _wrap(dek: bytes, version: str) -> str:
    nonce = os.urandom(12)
    return base64.b64encode(nonce + AESGCM(_KEKS[version]).encrypt(nonce, dek, b"dek")).decode()


def _unwrap(wrapped: str, version: str) -> bytes:
    blob = base64.b64decode(wrapped)
    return AESGCM(_KEKS[version]).decrypt(blob[:12], blob[12:], b"dek")


def rewrap(wrapped: str, old_version: str, new_version: str) -> str:
    return _wrap(_unwrap(wrapped, old_version), new_version)


class StoredBlob:
    def __init__(self, key: str, wrapped_dek: str, kek_version: str, sha256: str, size: int):
        self.key, self.wrapped_dek, self.kek_version, self.sha256, self.size = key, wrapped_dek, kek_version, sha256, size


def put(data: bytes, owner_id: str) -> StoredBlob:
    dek = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    sha = hashlib.sha256(data).hexdigest()
    ct = AESGCM(dek).encrypt(nonce, data, owner_id.encode())
    key = f"{owner_id}/{os.urandom(8).hex()}.bin"
    path = _STORE / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(nonce + ct)
    ver = active_kek_version()
    return StoredBlob(key, _wrap(dek, ver), ver, sha, len(data))


def get(key: str, wrapped_dek: str, kek_version: str, owner_id: str) -> bytes:
    blob = (_STORE / key).read_bytes()
    dek = _unwrap(wrapped_dek, kek_version)
    return AESGCM(dek).decrypt(blob[:12], blob[12:], owner_id.encode())


def tokenize(value: str, purpose: str) -> str:
    """Irreversible keyed token (HMAC-SHA256) used instead of raw identity numbers."""
    import hmac
    k = _KEKS[list(_KEKS.keys())[0]]
    return hmac.new(k, f"{purpose}:{value}".encode(), hashlib.sha256).hexdigest()


def mask_aadhaar(num: str) -> str:
    d = "".join(c for c in num if c.isdigit())
    return f"XXXX-XXXX-{d[-4:]}" if len(d) >= 4 else ""


def mask_pan(pan: str) -> str:
    pan = pan.upper()
    return f"{pan[:2]}XXXXX{pan[-3:]}" if len(pan) == 10 else ""


def seal_field(value: str, owner_id: str) -> str:
    """Field-level envelope encryption for small secrets (e.g. full PAN)."""
    import json
    dek = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    ct = AESGCM(dek).encrypt(nonce, value.encode(), owner_id.encode())
    ver = active_kek_version()
    return json.dumps({"c": base64.b64encode(nonce + ct).decode(), "k": _wrap(dek, ver), "v": ver})


def open_field(sealed: str, owner_id: str) -> str:
    import json
    if not sealed:
        return ""
    o = json.loads(sealed)
    blob = base64.b64decode(o["c"])
    return AESGCM(_unwrap(o["k"], o["v"])).decrypt(blob[:12], blob[12:], owner_id.encode()).decode()


def reseal_field(sealed: str, new_version: str) -> str:
    import json
    if not sealed:
        return sealed
    o = json.loads(sealed)
    if o["v"] == new_version:
        return sealed
    o["k"], o["v"] = rewrap(o["k"], o["v"], new_version), new_version
    return json.dumps(o)
