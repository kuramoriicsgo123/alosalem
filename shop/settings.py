"""Strict local configuration checks, with no Discord connection or secrets."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from . import SERVER_TYPE


class ConfigurationError(ValueError):
    """An actionable, safe-to-display configuration error."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigurationError(message)


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Fichier manquant : {path.name}") from exc
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ConfigurationError(f"JSON invalide dans {path.name} : {exc}") from exc


def _url(value, label: str) -> None:
    _require(isinstance(value, str), f"{label} doit être du texte.")
    if value:
        parsed = urlparse(value)
        _require(parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username,
                 f"{label} doit être une URL HTTPS publique, sans identifiants.")
        _require(len(value) <= 2000, f"{label} : URL trop longue.")


@dataclass(frozen=True)
class Settings:
    root: Path
    config: dict
    products: dict[str, dict]
    prices: dict
    structure: list[dict]

    @property
    def data_dir(self) -> Path:
        return (self.root / self.config["data_dir"]).resolve()


def load_settings(root: Path, *, require_config: bool = False) -> Settings:
    try:
        return _load_settings(root, require_config=require_config)
    except (TypeError, KeyError, AttributeError) as exc:
        raise ConfigurationError("Structure JSON invalide. Comparez vos objets, listes et champs avec les fichiers exemples.") from exc


def _load_settings(root: Path, *, require_config: bool = False) -> Settings:
    root = root.resolve()
    config_path = root / "config.json"
    if not config_path.exists():
        _require(not require_config,
                 "Copiez config.example.json vers config.json et renseignez guild_id et application_id.")
        config_path = root / "config.example.json"
    defaults = _read(root / "config.example.json")
    selected = _read(config_path)
    _require(isinstance(defaults, dict) and isinstance(selected, dict), "La configuration doit être un objet JSON.")
    config = {**defaults, **selected}
    _require(not any("token" in key.lower() for key in config),
             "Placez le token uniquement dans .env (DISCORD_TOKEN), jamais dans config.json.")
    for key in ("guild_id", "application_id"):
        value = config.get(key)
        _require(type(value) is int and 0 <= value < 2**64,
                 f"{key} doit être un identifiant Discord numérique, sans guillemets.")
        if require_config:
            _require(value > 0, f"Renseignez {key} dans config.json.")
    _require(isinstance(config.get("shop_name"), str) and 1 <= len(config["shop_name"]) <= 100,
             "shop_name doit contenir entre 1 et 100 caractères.")
    _require(isinstance(config.get("accent_color"), str)
             and re.fullmatch(r"#?[0-9A-Fa-f]{6}", config["accent_color"]) is not None,
             "accent_color doit être une couleur hexadécimale à 6 caractères.")
    coin = config.get("coin_emoji")
    _require(isinstance(coin, str) and (coin == "🪙" or re.fullmatch(r"<a?:\w{2,32}:\d{15,22}>", coin)),
             "coin_emoji : utilisez 🪙 ou le format Discord <:coin:IDENTIFIANT>.")
    for key in ("logo_url", "banner_url"):
        _url(config.get(key, ""), key)
    allowed_roles = {"owner", "admin", "moderator", "seller"}
    for key in ("staff_role_keys", "manager_role_keys"):
        values = config.get(key)
        _require(isinstance(values, list) and values and all(isinstance(v, str) for v in values) and set(values) <= allowed_roles,
                 f"{key} doit contenir uniquement owner, admin, moderator ou seller.")
    _require(set(config["manager_role_keys"]) <= {"owner", "admin"},
             "Seuls owner et admin peuvent gérer les panneaux et annonces.")
    _require(set(config["manager_role_keys"]) <= set(config["staff_role_keys"]),
             "Les responsables doivent aussi figurer dans staff_role_keys.")
    for key, low, high in (("ticket_cooldown_seconds", 1, 3600), ("max_open_tickets_per_user", 1, 10),
                           ("ticket_category_capacity", 1, 45), ("transcript_limit", 100, 100000)):
        _require(type(config.get(key)) is int and low <= config[key] <= high,
                 f"{key} doit être un entier entre {low} et {high}.")
    _require(isinstance(config.get("data_dir"), str) and bool(config["data_dir"]), "data_dir est invalide.")
    data_path = (root / config["data_dir"]).resolve()
    _require(data_path.is_relative_to(root) and data_path != root,
             "data_dir doit être un sous-dossier du projet.")

    structure = _read(root / "structure.json")
    _require(isinstance(structure, list) and 1 <= len(structure) <= 30, "structure.json doit lister les catégories.")
    categories, channel_keys, channel_names = set(), set(), set()
    central_count = 0
    for category in structure:
        _require(isinstance(category, dict), "Catégorie invalide.")
        key = category.get("key", "")
        _require(isinstance(key, str) and re.fullmatch(r"[a-z0-9-]{1,60}", key) and key not in categories,
                 f"Clé de catégorie invalide ou dupliquée : {key}")
        categories.add(key)
        _require(isinstance(category.get("name"), str) and 1 <= len(category["name"]) <= 100,
                 f"Nom de catégorie invalide : {key}")
        _require(isinstance(category.get("channels"), list), f"Liste de salons manquante : {key}")
        for channel in category["channels"]:
            _require(isinstance(channel, dict), f"Salon invalide dans {key}.")
            ck, name = channel.get("key", ""), channel.get("name", "")
            _require(ck and ck not in channel_keys, f"Clé de salon vide ou dupliquée : {ck}")
            _require(isinstance(name, str) and 1 <= len(name) <= 100 and name not in channel_names,
                     f"Nom de salon invalide ou dupliqué : {name}")
            _require(channel.get("mode") in {"readonly", "community", "staff"}, f"Mode invalide : {ck}")
            channel_keys.add(ck)
            channel_names.add(name)
            central_count += ck == "open-a-ticket"
    _require(central_count == 1, "Il faut exactement un salon open-a-ticket dans structure.json.")
    raw_products = _read(root / "products.json")
    _require(isinstance(raw_products, list) and raw_products, "products.json doit lister les produits.")
    products = {}
    kinds = {"boss", "dedi", "dino", "base", "advertisement", "item", "note", "service"}
    for product in raw_products:
        _require(isinstance(product, dict), "Produit invalide.")
        pid = product.get("id", "")
        _require(isinstance(pid, str) and re.fullmatch(r"[a-z0-9-]{1,60}", pid) and pid not in products,
                 f"Identifiant produit invalide ou dupliqué : {pid}")
        _require(product.get("category") in categories, f"Catégorie inconnue : {pid}")
        _require(product.get("kind") in kinds, f"Type inconnu : {pid}")
        for key, limit in (("title", 256), ("description", 3500), ("button_label", 80), ("availability", 800)):
            _require(isinstance(product.get(key), str) and 1 <= len(product[key]) <= limit,
                     f"{pid}.{key} doit contenir entre 1 et {limit} caractères.")
        name = product.get("channel")
        if name:
            _require(isinstance(name, str) and len(name) <= 100 and name not in channel_names and pid not in channel_keys,
                     f"Salon de produit dupliqué ou invalide : {pid}")
            channel_names.add(name)
            channel_keys.add(pid)
        fields = product.get("fields", [])
        _require(type(product.get("commercial", True)) is bool, f"{pid}.commercial doit être true ou false.")
        _require(isinstance(fields, list) and len(fields) <= 17, f"Trop de champs : {pid}")
        for field in fields:
            _require(isinstance(field, dict), f"Champ invalide : {pid}")
            for key, limit in (("name", 256), ("value", 1024)):
                _require(isinstance(field.get(key), str) and 1 <= len(field[key]) <= limit,
                         f"Champ {pid}.{key} trop long ou vide.")
        _url(product.get("image_url", ""), f"{pid}.image_url")
        stats = product.get("stats", {})
        _require(isinstance(stats, dict), f"{pid}.stats doit être un objet JSON.")
        for key, value in stats.items():
            _require(value is None or type(value) in (str, int, float, list), f"Statistique invalide : {pid}.{key}")
            _require(len(str(value)) <= 500, f"Statistique trop longue : {pid}.{key}")
        screenshots = product.get("screenshots", [])
        _require(isinstance(screenshots, list) and len(screenshots) <= 5, f"{pid}.screenshots doit contenir au maximum cinq URLs.")
        for url in screenshots:
            _url(url, f"{pid}.screenshots")
        _require(sum(len(url) + 25 for url in screenshots) <= 1000, f"Liens de captures trop longs : {pid}.")
        products[pid] = product
    _require(len(channel_keys) + len(categories) < 400, "Trop de salons : gardez une marge pour les tickets Discord.")
    for category in categories:
        count = sum(1 for p in products.values() if p["category"] == category and p.get("channel"))
        count += next(len(c["channels"]) for c in structure if c["key"] == category)
        _require(count <= 45, f"Trop de salons dans {category} (maximum boutique : 45).")

    prices = _read(root / "prices.json")
    _require(isinstance(prices, dict) and prices.get("currency") in {"EUR", "USD", "GBP"},
             "prices.json : currency doit être EUR, USD ou GBP.")
    entries = prices.get("products")
    _require(isinstance(entries, dict), "prices.json : products doit être un objet.")
    _require(not set(entries) - set(products), "prices.json contient des identifiants produits inconnus.")
    for pid in products:
        servers = entries.get(pid)
        _require(isinstance(servers, dict) and set(servers) == {SERVER_TYPE},
                 f"prices.json : {pid} doit contenir uniquement le groupe {SERVER_TYPE}. "
                 "Mettez à jour prices.json pour la boutique Small Tribes.")
        for server, variants in servers.items():
            minimum = 0 if products[pid].get("commercial") is False else 1
            _require(isinstance(variants, dict) and minimum <= len(variants) <= 10, f"Variantes de prix invalides : {pid}")
            for label, value in variants.items():
                _require(isinstance(label, str) and 1 <= len(label) <= 60, f"Libellé de prix invalide : {pid}")
                _require(value is None or (type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1000000),
                         f"Prix invalide : {pid}/{server}/{label}. Utilisez un nombre positif ou null.")
    return Settings(root, config, products, prices, structure)
