from secrets import token_urlsafe

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type

# Argon2id：19 MiB 内存、两次迭代、单路并行；每次自动生成独立盐。
hasher = PasswordHasher(
    time_cost=2, memory_cost=19456, parallelism=1,
    hash_len=32, salt_len=16, type=Type.ID,
)
_dummy_hash = hasher.hash(token_urlsafe(32))


def hash_password(password: str) -> str:
    return hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        valid = hasher.verify(password_hash or _dummy_hash, password)
        return bool(password_hash) and valid
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return hasher.check_needs_rehash(password_hash)
