"""Getypeerde installatieconfiguratie en write-only versleutelde providerkeys."""
from __future__ import annotations

import base64
from typing import Literal
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from .config import env


class SettingsSecretError(ValueError):
    """Secretopslag is niet beschikbaar; de fout bevat nooit invoerwaarden."""


def settings_cipher() -> Fernet:
    secret = env('BETONNING_SETTINGS_SECRET')
    if secret is None:
        secret = env('BETONNING_MEDIA_SECRET')
    if not secret or len(secret) < 32:
        raise SettingsSecretError('Configureer een duurzame settings- of media-secret van minimaal 32 tekens')
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
               info=b'hegemone:installation-secrets:v1').derive(secret.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def decrypt_key(value: bytes | None) -> str | None:
    if not value:
        return None
    try:
        return settings_cipher().decrypt(value).decode()
    except (InvalidToken, UnicodeDecodeError):
        raise SettingsSecretError('Opgeslagen providerkey kan niet worden ontsleuteld') from None


def valid_url(value: str) -> str:
    if not value:
        return ''
    try:
        if value != value.strip() or any(char.isspace() for char in value):
            raise ValueError
        url = urlsplit(value)
        if url.scheme not in {'https', 'http'} or not url.hostname or url.username is not None or url.password is not None or url.query or url.fragment or url.port == 0:
            raise ValueError
    except ValueError:
        raise ValueError('Gebruik een http(s)-URL zonder credentials, query of fragment') from None
    return value.rstrip('/')


class ProviderSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    base_url: str = Field(default='', max_length=2048)
    model: str = Field(default='', max_length=100)
    timeout: float = Field(default=60, ge=1, le=120, allow_inf_nan=False)

    _url = field_validator('base_url')(valid_url)


class ProviderPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool | None = None
    base_url: str | None = Field(default=None, max_length=2048)
    model: str | None = Field(default=None, max_length=100)
    timeout: float | None = Field(default=None, ge=1, le=120, allow_inf_nan=False)
    api_key: SecretStr | None = Field(default=None, max_length=8192)

    @field_validator('api_key')
    @classmethod
    def valid_key(cls, value):
        if value is not None:
            text = value.get_secret_value()
            if text and (not text.isascii() or any(char.isspace() for char in text)):
                raise ValueError('Providerkey mag geen whitespace of niet-ASCII-tekens bevatten')
        return value


class InstallationSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    language: Literal['en', 'nl'] = 'en'
    ai_language: Literal['en', 'nl'] = 'en'
    public_url: str = Field(default='http://localhost:8000', min_length=1, max_length=2048)
    llm: ProviderSettings = Field(default_factory=ProviderSettings)
    embedding: ProviderSettings = Field(default_factory=lambda: ProviderSettings(timeout=30))
    triage_enabled: bool = False
    wiki_compile_enabled: bool = False

    _url = field_validator('public_url')(valid_url)


class InstallationPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    language: Literal['en', 'nl'] | None = None
    ai_language: Literal['en', 'nl'] | None = None
    public_url: str | None = Field(default=None, min_length=1, max_length=2048)
    llm: ProviderPatch | None = None
    embedding: ProviderPatch | None = None
    triage_enabled: bool | None = None
    wiki_compile_enabled: bool | None = None


class InstallationUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal[1]
    expected_revision: int = Field(ge=0)
    settings: InstallationPatch


def merge_patch(current: dict, patch: InstallationPatch) -> tuple[dict, dict, list[str]]:
    """Valideer publieke velden; scheid keyacties zonder ze te serialiseren."""
    merged = InstallationSettings.model_validate(current).model_dump()
    keys = {}
    changed = []
    for name in patch.model_fields_set:
        value = getattr(patch, name)
        if name in {'llm', 'embedding'} and value is not None:
            for field in value.model_fields_set:
                setting = getattr(value, field)
                changed.append(f'{name}.{field}')
                if field == 'api_key':
                    keys[name] = setting.get_secret_value() if setting else None
                else:
                    merged[name][field] = setting
        else:
            merged[name] = value
            changed.append(name)
    return InstallationSettings.model_validate(merged).model_dump(), keys, sorted(changed)


def public_settings(row: dict | None) -> dict:
    settings = InstallationSettings.model_validate(row['settings'] if row else {}).model_dump()
    for name, column in [('llm', 'llm_key'), ('embedding', 'embedding_key')]:
        settings[name]['has_api_key'] = bool(row and row[column])
    try:
        settings_cipher()
        ready = True
    except SettingsSecretError:
        ready = False
    return {'schema_version': 1, 'revision': row['revision'] if row else 0,
            'settings': settings, 'secret_storage_ready': ready,
            'updated_at': row['updated_at'] if row else None,
            'updated_by': row['updated_by'] if row else None}
