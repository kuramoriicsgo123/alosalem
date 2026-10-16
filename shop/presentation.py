"""Discord presentation, kept separate from network and persistence code."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import discord

from . import SERVER_TYPE


FIXED_PRICE_RULE = "All prices are fixed and non-negotiable."
SERVER_TYPES = (SERVER_TYPE,)
ORDER_INSTRUCTIONS = (
    "Click the green button below to open a private ticket for this product. "
    "This shop serves ASA Small Tribes only. "
    "Provide your quantity, map, Small Tribes server number and order details.\n\n"
    f"**{FIXED_PRICE_RULE}**\n"
    "Where a price says Contact Staff, staff will confirm a fixed price before you commit."
)


def panel_marker(kind: str, key: str) -> str:
    """Stable identifiers also allow recovery after loss of the local database."""
    return f"ASA-SHOP|{kind}|{key}"


def format_price(value: Any, settings: Any) -> str:
    coin = settings.config.get("coin_emoji") or "🪙"
    currency = settings.prices.get("currency", "EUR")
    if value is None or value == "" or value == "Contact Staff":
        amount = "Contact Staff"
    elif isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        number = f"{Decimal(str(value)):,.2f}".rstrip("0").rstrip(".")
        amount = f"{number} {'€' if currency == 'EUR' else currency}"
    else:
        # Config validation rejects unsupported prices; remain safe in previews.
        amount = "Contact Staff"
    return f"{coin} {amount}"


def _brand(settings: Any, title: str, description: str, kind: str, key: str) -> discord.Embed:
    color = int(str(settings.config.get("accent_color", "B3202A")).lstrip("#"), 16)
    embed = discord.Embed(title=title[:256], description=description[:4096], color=color)
    shop_name = str(settings.config.get("shop_name", "ASA Shop"))
    embed.set_author(name=shop_name[:256])
    logo = settings.config.get("logo_url")
    if logo:
        embed.set_thumbnail(url=logo)
    embed.set_footer(text=f"{shop_name[:128]} • {panel_marker(kind, key)}")
    return embed


def _add_field(embed: discord.Embed, name: str, value: Any, inline: bool = False) -> None:
    """Respect both individual and aggregate Discord embed limits."""
    if len(embed.fields) >= 25:
        return
    name = str(name)[:256] or "Details"
    value = str(value) or "To be added"
    remaining = 5900 - len(embed) - len(name)
    if remaining < 8:
        return
    limit = min(1024, remaining)
    if len(value) > limit:
        value = value[: limit - 1] + "…"
    embed.add_field(name=name, value=value, inline=inline)


def build_product_embed(settings: Any, product_id: str) -> discord.Embed:
    product = settings.products[product_id]
    # Calculate all price fields before optional prose. Truncating a long price
    # group could otherwise hide a variant or even cut an amount in half.
    essential_fields: list[tuple[str, str]] = []
    commercial = product.get("commercial", True)
    prices = settings.prices.get("products", {}).get(product_id, {}) if commercial else {}
    for server_type in SERVER_TYPES:
        variants = prices.get(server_type)
        if not isinstance(variants, dict) or not variants:
            continue
        lines = [f"**{name}** — {format_price(price, settings)}" for name, price in variants.items()]
        chunks: list[str] = []
        chunk = ""
        for line in lines:
            if len(line) > 1024:
                raise ValueError(f"Price label too long for {product_id}/{server_type}.")
            if chunk and len(chunk) + len(line) + 1 > 1024:
                chunks.append(chunk)
                chunk = ""
            chunk += ("\n" if chunk else "") + line
        if chunk:
            chunks.append(chunk)
        for index, value in enumerate(chunks):
            name = server_type if index == 0 else f"{server_type} (continued)"
            essential_fields.append((name, value))
    if not essential_fields and commercial:
        essential_fields.append(("Price", format_price(None, settings)))
    essential_fields.extend([
        ("Availability", product.get("availability") or "Contact staff to confirm current stock and server compatibility."),
        ("How to order" if commercial else "How to contact staff", ORDER_INSTRUCTIONS if commercial else
         "Click the green button below to open a private ticket for this request. No purchase is required. "
         "Describe your question or provide the relevant information for staff."),
    ])
    embed = _brand(settings, product["title"], "", "product", product_id)
    reserved = sum(len(name) + len(value) for name, value in essential_fields)
    remaining = 5900 - len(embed) - reserved
    if remaining < 64 or len(essential_fields) > 24:
        raise ValueError(f"Too much pricing text for {product_id}; shorten variant labels or the availability text.")
    description = str(product.get("description", ""))
    description_limit = min(1800, remaining)
    if len(description) > description_limit:
        description = description[:description_limit - 1] + "…"
    embed.description = description
    remaining -= len(description)
    fields = [dict(field) for field in product.get("fields", [])]
    stats = product.get("stats", {})
    stat_names = {"Level": "level", "Health (HP)": "hp", "Melee Damage": "melee", "Mutations": "mutations", "Available Colors": "colors"}
    screenshots = product.get("screenshots", [])
    for field in fields:
        stat = stats.get(stat_names.get(field["name"], ""))
        if stat is not None and stat != [] and stat != "":
            field["value"] = ", ".join(str(item) for item in stat) if isinstance(stat, list) else str(stat)
        if field["name"] == "Screenshots" and screenshots:
            field["value"] = "\n".join(f"[Screenshot {index}]({url})" for index, url in enumerate(screenshots, 1))
    if screenshots and not any(field["name"] == "Screenshots" for field in fields):
        fields.append({"name": "Screenshots", "value": "\n".join(f"[Screenshot {index}]({url})" for index, url in enumerate(screenshots, 1))})
    for field in fields:
        if len(embed.fields) >= 25 - len(essential_fields) or remaining <= len(field["name"]) + 8:
            break
        name = str(field["name"])[:256]
        value = str(field["value"])
        limit = min(1024, remaining - len(name))
        if len(value) > limit:
            value = value[:limit - 1] + "…"
        embed.add_field(name=name, value=value, inline=bool(field.get("inline", False)))
        remaining -= len(name) + len(value)
    for name, value in essential_fields:
        embed.add_field(name=name, value=value, inline=False)
    image = product.get("image_url") or (screenshots[0] if screenshots else None) or settings.config.get("banner_url")
    if image:
        embed.set_image(url=image)
    return embed


def build_information_embed(settings: Any, channel: dict[str, Any]) -> discord.Embed:
    key = channel["key"]
    embed = _brand(
        settings,
        channel.get("title", channel["name"]),
        channel.get("description", ""),
        "info",
        key,
    )
    banner = settings.config.get("banner_url")
    if banner and key in {"welcome", "shop-catalog", "open-a-ticket"}:
        embed.set_image(url=banner)
    for field in channel.get("fields", []):
        _add_field(embed, field["name"], field["value"], bool(field.get("inline", False)))
    return embed
