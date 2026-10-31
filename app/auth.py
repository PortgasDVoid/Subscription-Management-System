"""Password policy, hashing and a small HS256 token implementation (stdlib only)."""
import base64, hashlib, hmac, json, os, re, secrets, time

SECRET = os.getenv("JWT_SECRET") or secrets.token_hex(32)   # set JWT_SECRET so tokens survive restarts
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalise_email(value: str) -> str:
    value = (value or "").strip().lower()
    if not EMAIL_RE.match(value):
        raise ValueError("Enter a valid email address")
    return value


def password_problems(pw: str) -> list:
    """Brief: more than eight characters, an uppercase, a lowercase and a special character."""
    problems = []
    if not pw or len(pw) <= 8: problems.append("must be more than 8 characters")
    if not any(c.isupper() for c in pw or ""): problems.append("needs an uppercase letter")
    if not any(c.islower() for c in pw or ""): problems.append("needs a lowercase letter")
    if not any(not c.isalnum() for c in pw or ""): problems.append("needs a special character")
    return problems


def hash_password(pw: str) -> str:
    try:
        import bcrypt
        return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(12)).decode()   # schema: bcrypt / Argon2 only
    except ImportError:                                                  # dev/test fallback
        salt = os.urandom(16)
        return "scrypt$" + salt.hex() + "$" + hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1).hex()


def verify_password(pw: str, stored: str) -> bool:
    if not stored: return False
    if stored.startswith("scrypt$"):
        try:
            _, salt, digest = stored.split("$")
            calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()
            return hmac.compare_digest(calc, digest)
        except Exception:
            return False
    if stored.startswith("$2"):
        try:
            import bcrypt
            return bcrypt.checkpw(pw.encode(), stored.encode())
        except Exception:
            return False
    return False


def _b64(b: bytes) -> str: return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
def _unb64(s: str) -> bytes: return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(user_id: int, role: str, ttl: int = 8 * 3600) -> str:
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps({"sub": user_id, "role": role, "exp": int(time.time()) + ttl}, separators=(",", ":")).encode())
    sig = _b64(hmac.new(SECRET.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest())
    return f"{head}.{body}.{sig}"


def decode_token(token: str):
    try:
        head, body, sig = token.split(".")
        good = _b64(hmac.new(SECRET.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good): return None
        claims = json.loads(_unb64(body))
        return claims if claims.get("exp", 0) > time.time() else None
    except Exception:
        return None


def new_reset_token():
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def hash_token(raw: str) -> str: return hashlib.sha256(raw.encode()).hexdigest()
