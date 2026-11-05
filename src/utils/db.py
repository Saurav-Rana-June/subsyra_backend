import socket
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from src.utils.settings import settings

# Fallback for Windows DNS intermittent failure with Neon tech domains
_orig_getaddrinfo = socket.getaddrinfo


def _custom_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    try:
        return _orig_getaddrinfo(host, port, family, type, proto, flags)
    except socket.gaierror:
        if isinstance(host, str) and "neon.tech" in host:
            return _orig_getaddrinfo("3.14.138.241", port, family, type, proto, flags)
        raise


socket.getaddrinfo = _custom_getaddrinfo

Base = declarative_base()

engine = create_engine(url=settings.DB_CONNECTION)

LocalSession = sessionmaker(bind=engine)


def get_db():
    session = LocalSession()

    try:
        yield session
    finally:
        session.close()
