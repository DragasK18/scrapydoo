"""
Autenticación, roles y auditoría de conexiones.

Sesión basada en cookies de Flask con contraseñas hasheadas (werkzeug).
Un usuario con rol "admin" gestiona usuarios y consulta el registro de accesos.
"""
from __future__ import annotations

import os
from typing import Optional

import requests
from flask import session
from werkzeug.security import check_password_hash, generate_password_hash

from database import repository

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
DEFAULT_ADMIN_PASSWORD = "admin123"


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, password)


def current_user() -> Optional[dict]:
    if "user_id" not in session:
        return None
    return repository.get_user_by_id(session["user_id"])


def authenticate(username: str, password: str) -> Optional[dict]:
    """Verifica usuario/contraseña y devuelve el usuario (sin el hash) si es válido."""
    user = repository.get_user_auth(username)
    if user and user.get("is_active") and verify_password(password, user["password_hash"]):
        return {k: v for k, v in user.items() if k != "password_hash"}
    return None


def is_admin() -> bool:
    user = current_user()
    return bool(user and user.get("role") == "admin")


def geolocate(ip: str) -> str:
    """Resuelve ciudad/región/país de una IP (mejor esfuerzo, sin bloquear)."""
    if not ip or ip in ("127.0.0.1", "::1", "localhost"):
        return "Local"
    try:
        resp = requests.get(f"http://ip-api.com/json/{ip}", timeout=2)
        data = resp.json()
        if data.get("status") == "success":
            partes = [p for p in (data.get("city"), data.get("regionName"), data.get("country")) if p]
            texto = ", ".join(partes)
            isp = data.get("isp")
            if isp:
                texto = f"{texto} · {isp}" if texto else isp
            return texto or "—"
    except Exception:  # noqa: BLE001
        pass
    return "—"


def record_login(username: str, success: bool, ip: str = "", user_agent: str = "") -> None:
    """Guarda un intento de acceso en la bitácora."""
    location = geolocate(ip) if (success and ip) else None
    try:
        repository.add_login_log(username, success, ip=ip, user_agent=user_agent, location=location)
    except Exception:  # noqa: BLE001
        pass


def seed_admin() -> bool:
    """Crea el administrador inicial si no hay usuarios. Devuelve True si creó."""
    if repository.count_users() == 0:
        repository.create_user(
            ADMIN_USERNAME,
            hash_password(ADMIN_PASSWORD),
            full_name="Administrador",
            role="admin",
        )
        return True
    return False


def is_default_admin_password() -> bool:
    """True si el admin sigue usando la contraseña por defecto."""
    user = repository.get_user_auth(ADMIN_USERNAME)
    if not user:
        return False
    return verify_password(DEFAULT_ADMIN_PASSWORD, user["password_hash"])
