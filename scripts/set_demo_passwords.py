"""Give every seeded demo user the documented password (Password@123) using this app's own hashing.
Run once after seeding if the seeded bcrypt hash does not match:  python -m scripts.set_demo_passwords"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text
from app.auth import hash_password
from app.deps import engine

with engine.begin() as c:
    n = c.execute(text("UPDATE users SET password_hash=:h, failed_logins=0, locked_until=NULL WHERE email LIKE '%.test'"),
                  {"h": hash_password("Password@123")}).rowcount
print(f"Updated {n} demo users to Password@123")
