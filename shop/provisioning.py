"""Repeatable provisioning of this shop's Discord objects and persistent panels.

Only objects identified by a saved ID, our marker, or an unambiguous configured
name are managed. Unknown objects are never deleted.
"""

from __future__ import annotations

import re
from typing import Any

import discord

from . import __version__
from .presentation import build_information_embed, build_product_embed, panel_marker


ROLE_NAMES = {
    "owner": "👑 Owner",
    "admin": "🛡️ Admin",
    "moderator": "🔨 Moderator",
    "seller": "🛒 Seller",
    "vip": "💎 VIP",
    "customer": "⭐ Customer",
    "bots": "🤖 Bots",
}

ROLE_COLORS = {
    "owner": 0xD6A83C,
    "admin": 0xB3202A,
    "moderator": 0xC95656,
    "seller": 0x3A9D65,
    "vip": 0x805AD5,
    "customer": 0x3498DB,
    "bots": 0x7289DA,
}

REQUIRED_BOT_PERMISSIONS = (
    "manage_roles", "manage_channels", "view_channel", "send_messages",
    "embed_links", "attach_files", "read_message_history", "add_reactions",
    # Discord checks permissions that an overwrite denies as well as allows:
    # https://docs.discord.com/developers/resources/guild#create-guild-channel
    "mention_everyone", "create_public_threads", "create_private_threads",
    "send_messages_in_threads",
)

PERMISSION_LABELS = {
    "manage_roles": "Gérer les rôles", "manage_channels": "Gérer les salons",
    "view_channel": "Voir les salons", "send_messages": "Envoyer des messages",
    "read_messages": "Voir les salons",  # Canonical name yielded by Permissions.__iter__.
    "embed_links": "Intégrer des liens", "attach_files": "Joindre des fichiers",
    "read_message_history": "Voir les anciens messages", "add_reactions": "Ajouter des réactions",
    "mention_everyone": "Mentionner @everyone, @here et tous les rôles",
    "create_public_threads": "Créer des fils publics",
    "create_private_threads": "Créer des fils privés",
    "send_messages_in_threads": "Envoyer des messages dans les fils",
}


class ProvisioningError(RuntimeError):
    """Actionable setup failure that is safe to show to the server owner."""


def _channel_forbidden(guild: discord.Guild, category: discord.CategoryChannel,
                       channel: discord.TextChannel | None, overwrites: dict,
                       exc: discord.Forbidden, *, channel_name: str) -> ProvisioningError:
    """Describe only permission state and the failed setup route, never secrets.

    These observations come from discord.py's cached objects. They help locate
    the failure but cannot substitute for Discord's server-side authorization.
    """
    operation = "création" if channel is None else "modification"
    lines = [
        f"Discord refuse l'étape : {operation} du salon {channel_name} "
        f"(HTTP {exc.status}, code {exc.code}).",
        f"Version du bot : {__version__}",
    ]
    response = exc.response
    method = getattr(response, "method", None)
    path = getattr(getattr(response, "url", None), "path", "")
    # Restrict output to channel setup routes; never dump a URL query, headers,
    # exception body, or a different route that could contain a credential.
    if isinstance(path, str) and method in ("POST", "PATCH", "PUT"):
        match = re.fullmatch(r"(?:/api/v\d+)?(/(?:guilds/\d+/channels|channels/\d+))", path)
        if match:
            route = re.sub(r"\d+", "{id}", match.group(1))
            lines.append(f"Requête refusée : {method} {route}")
    lines.append("Permissions observées dans le cache Discord (diagnostic, pas une preuve de la cause) :")
    member = guild.me
    if member is not None:
        requested = discord.Permissions.none()
        for overwrite in overwrites.values():
            allow, deny = overwrite.pair()
            requested.value |= allow.value | deny.value

        def missing_names(permissions: discord.Permissions, names: list[str] | tuple[str, ...]) -> str:
            missing = [PERMISSION_LABELS.get(name, name) for name in names
                       if not getattr(permissions, name)]
            return ", ".join(missing) or "aucune permission requise manquante"

        lines.append("Au niveau du serveur : " + missing_names(member.guild_permissions, REQUIRED_BOT_PERMISSIONS))
        channel_requirements = [name for name, enabled in requested if enabled]
        # Creating/updating a child also needs channel/permission management.
        channel_requirements = list(dict.fromkeys(channel_requirements + ["manage_channels", "manage_roles"]))
        lines.append(f"Dans la catégorie {category.name} : " + missing_names(
            category.permissions_for(member), channel_requirements))
        if channel is not None:
            lines.append(f"Dans le salon {channel.name} : " + missing_names(
                channel.permissions_for(member), channel_requirements))
        lines.append(f"Rôle le plus haut du bot : {member.top_role.name} (ID {member.top_role.id})")
    lines.append("Les éléments déjà créés sont conservés. Gardez ces lignes pour le diagnostic ; "
                 "ne modifiez pas votre token pour cette erreur de permissions.")
    return ProvisioningError("\n".join(lines))


def _role_permissions(key: str) -> discord.Permissions:
    # Shop authority comes from channel overrides and bot authorization checks.
    # Never give a newly-created shop role server-wide powers, and never attempt
    # to grant powers that the bot itself was deliberately not invited with.
    return discord.Permissions.none()


def _preflight(guild: discord.Guild) -> discord.Member:
    member = guild.me
    if member is None:
        raise ProvisioningError("Bot member unavailable. Wait for Discord to finish connecting, then retry.")
    missing = [name for name in REQUIRED_BOT_PERMISSIONS if not getattr(member.guild_permissions, name)]
    if missing:
        raise ProvisioningError(
            "Permissions manquantes pour le bot : " + ", ".join(PERMISSION_LABELS[name] for name in missing)
            + ". Dans Discord : Paramètres du serveur → Rôles → rôle portant le nom du bot → Permissions. "
            "Activez ces permissions, enregistrez et relancez. Discord exige aussi les permissions "
            "que le bot doit interdire aux membres. Administrator est inutile."
        )
    return member


def _only_match(matches: list[Any], description: str) -> Any | None:
    if len(matches) > 1:
        raise ProvisioningError(
            f"Several {description} exist. Rename the duplicate objects in Discord before syncing; "
            "the bot will not guess or delete them."
        )
    return matches[0] if matches else None


def _overwrites(bot: Any, guild: discord.Guild, roles: dict[str, discord.Role], mode: str) -> dict[Any, discord.PermissionOverwrite]:
    is_staff = mode == "staff"
    is_community = mode == "community"
    overwrites: dict[Any, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=not is_staff,
            read_message_history=not is_staff,
            send_messages=is_community,
            embed_links=is_community,
            attach_files=is_community,
            add_reactions=is_community,
            create_public_threads=False,
            create_private_threads=False,
            send_messages_in_threads=False,
            mention_everyone=False,
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=True,
            embed_links=True, attach_files=True, manage_channels=True, add_reactions=True,
            create_public_threads=True, create_private_threads=True,
            send_messages_in_threads=True, mention_everyone=True,
        ),
    }
    authorized = bot.settings.config.get(
        "staff_role_keys" if is_staff else "manager_role_keys",
        ["owner", "admin", "moderator", "seller"] if is_staff else ["owner", "admin"],
    )
    for key in authorized:
        if key not in roles:
            raise ProvisioningError(f"Unknown configured role key: {key!r}.")
        overwrites[roles[key]] = discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=True,
            embed_links=True, attach_files=True, add_reactions=True,
            mention_everyone=False,
        )
    return overwrites


async def _roles(bot: Any, guild: discord.Guild, summary: dict[str, int]) -> dict[str, discord.Role]:
    roles: dict[str, discord.Role] = {}
    member = _preflight(guild)
    # Refresh role state so checks use Discord's latest hierarchy.
    existing = await guild.fetch_roles()
    by_id = {role.id: role for role in existing}
    for key, name in ROLE_NAMES.items():
        saved = bot.store.get_resource("role", key)
        configured = bot.settings.config.get("role_ids", {}).get(key)
        role = by_id.get(int(configured or saved or 0))
        if configured and role is None:
            raise ProvisioningError(f"Configured role_ids.{key} does not exist in this server.")
        if role is None:
            role = _only_match([item for item in existing if item.name == name], f"roles named {name!r}")
        if role is not None:
            if role.is_default() or role.managed or role >= member.top_role:
                raise ProvisioningError(
                    f"The bot cannot manage {name!r}. Move its bot role above the shop roles "
                    "in Server Settings → Roles, then retry."
                )
            # Matching a name or explicit ID lets us reuse an existing role,
            # but is not permission to strip unrelated permissions from it.
            # Only roles we recorded as created by this bot are normalized.
            managed = bot.store.get_resource("managed_role", key) == role.id
            if not managed and role.permissions.administrator:
                raise ProvisioningError(
                    f"Existing role {name!r} has Administrator, which bypasses private channel permissions. "
                    "Remove that permission yourself or rename the existing role before using it as a shop role. "
                    "Its permissions were left unchanged."
                )
            permissions = _role_permissions(key)
            if managed and (role.name != name or role.permissions != permissions
                            or role.color.value != ROLE_COLORS[key] or role.mentionable):
                role = await role.edit(
                    name=name, permissions=permissions, color=discord.Color(ROLE_COLORS[key]),
                    mentionable=False, reason="ASA shop role synchronization",
                )
        else:
            role = await guild.create_role(
                name=name, permissions=_role_permissions(key), color=discord.Color(ROLE_COLORS[key]),
                mentionable=False, reason="ASA shop setup",
            )
            existing.append(role)
            bot.store.set_resource("managed_role", key, role.id)
            summary["roles_created"] += 1
        bot.store.set_resource("role", key, role.id)
        roles[key] = role
    return roles


async def _category(bot: Any, guild: discord.Guild, spec: dict[str, Any], position: int,
                    roles: dict[str, discord.Role], summary: dict[str, int]) -> discord.CategoryChannel:
    saved = bot.store.get_resource("category", spec["key"])
    category = guild.get_channel(saved) if saved else None
    if category is not None and not isinstance(category, discord.CategoryChannel):
        raise ProvisioningError(f"Saved category {spec['key']!r} points to a different channel type.")
    if category is None:
        category = _only_match([item for item in guild.categories if item.name == spec["name"]], f"categories named {spec['name']!r}")
    mode = "staff" if spec["key"] == "staff-only" else "community" if spec["key"] == "community" else "readonly"
    overwrites = _overwrites(bot, guild, roles, mode)
    if category is None:
        category = await guild.create_category(
            spec["name"], position=position, overwrites=overwrites, reason="ASA shop setup",
        )
        summary["categories_created"] += 1
    elif category.name != spec["name"] or category.overwrites != overwrites or category.position != position:
        category = await category.edit(
            name=spec["name"], position=position, overwrites=overwrites,
            reason="ASA shop category synchronization",
        )
    bot.store.set_resource("category", spec["key"], category.id)
    if spec["key"] == "tickets-services":
        bot.store.set_resource("category", "tickets", category.id)
    return category


async def _channel(bot: Any, guild: discord.Guild, category: discord.CategoryChannel,
                   spec: dict[str, Any], position: int, roles: dict[str, discord.Role],
                   summary: dict[str, int]) -> discord.TextChannel:
    key = spec["key"]
    marker = panel_marker("channel", key)
    saved = bot.store.get_resource("channel", key)
    channel = guild.get_channel(saved) if saved else None
    if channel is not None and not isinstance(channel, discord.TextChannel):
        raise ProvisioningError(f"Saved channel {key!r} points to a different channel type.")
    marked = [item for item in guild.text_channels if marker in (item.topic or "").splitlines()]
    recovered = _only_match(marked, f"channels with setup marker {key!r}")
    if channel is not None and recovered is not None and channel.id != recovered.id:
        raise ProvisioningError(f"Saved ID and recovery marker disagree for {key!r}; inspect the two channels before syncing.")
    if channel is None:
        channel = recovered
    if channel is None:
        channel = _only_match(
            [item for item in guild.text_channels if item.name == spec["name"] and item.category_id == category.id],
            f"channels named {spec['name']!r} in {category.name!r}",
        )
    if channel is not None:
        other_markers = [line for line in (channel.topic or "").splitlines() if line.startswith("ASA-SHOP|channel|") and line != marker]
        if other_markers:
            raise ProvisioningError(f"Channel {channel.name!r} belongs to another configured shop key.")
    # Preserve a pre-existing topic when adopting a channel by name.
    topic_lines = (channel.topic or "").splitlines() if channel is not None else []
    topic = "\n".join([line for line in topic_lines if line != marker] + [marker])
    if len(topic) > 1024:
        raise ProvisioningError(f"Shorten the topic of #{spec['name']} to leave room for its setup marker.")
    overwrites = _overwrites(bot, guild, roles, spec.get("mode", "readonly"))
    if channel is None:
        try:
            channel = await guild.create_text_channel(
                spec["name"], category=category, position=position, topic=topic,
                overwrites=overwrites, reason="ASA shop setup",
            )
        except discord.Forbidden as exc:
            raise _channel_forbidden(guild, category, None, overwrites, exc,
                                     channel_name=spec["name"]) from exc
        summary["channels_created"] += 1
    elif (channel.name != spec["name"] or channel.category_id != category.id
          or channel.topic != topic or channel.overwrites != overwrites or channel.position != position):
        try:
            channel = await channel.edit(
                name=spec["name"], category=category, position=position, topic=topic,
                overwrites=overwrites, reason="ASA shop channel synchronization",
            )
        except discord.Forbidden as exc:
            raise _channel_forbidden(guild, category, channel, overwrites, exc,
                                     channel_name=spec["name"]) from exc
    bot.store.set_resource("channel", key, channel.id)
    permissions = channel.permissions_for(guild.me)
    missing = [name for name in ("view_channel", "send_messages", "embed_links", "read_message_history") if not getattr(permissions, name)]
    if missing:
        raise ProvisioningError(f"Bot permissions still missing in #{channel.name}: {', '.join(missing)}.")
    return channel


def _has_marker(message: discord.Message, bot_id: int, marker: str) -> bool:
    return message.author.id == bot_id and any(
        embed.footer.text and embed.footer.text.endswith(" • " + marker)
        for embed in message.embeds
    )


def _comparable_payload(value: Any) -> Any:
    """Ignore metadata Discord adds, while retaining real emoji/custom IDs."""
    if isinstance(value, list):
        return [_comparable_payload(item) for item in value]
    if isinstance(value, dict):
        ignored = {"proxy_url", "proxy_icon_url", "width", "height"}
        if isinstance(value.get("type"), int):
            ignored.add("id")  # Auto-generated numeric component ID, not custom_id.
        return {key: _comparable_payload(item) for key, item in value.items() if key not in ignored}
    return value


async def _panel(bot: Any, channel: discord.TextChannel, key: str, kind: str,
                 embed: discord.Embed, view: discord.ui.View | None, summary: dict[str, int]) -> None:
    marker = panel_marker(kind, key)
    saved = bot.store.get_resource("panel", key)
    message = None
    if saved:
        try:
            candidate = await channel.fetch_message(saved)
        except discord.NotFound:
            pass
        else:
            if not _has_marker(candidate, bot.user.id, marker):
                raise ProvisioningError(f"Saved panel {key!r} does not identify a shop message. It was left untouched.")
            message = candidate
    if message is None:
        matches = []
        # Shop channels stay read-only; full history recovery prevents duplicates
        # even if staff announcements have pushed a panel out of the last page.
        async for candidate in channel.history(limit=None, oldest_first=True):
            if _has_marker(candidate, bot.user.id, marker):
                matches.append(candidate)
                if len(matches) > 1:
                    break
        message = _only_match(matches, f"panels for {key!r}")
    if message is None:
        message = await channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        summary["panels_created"] += 1
    else:
        expected_components = view.to_components() if view is not None else []
        current_components = [component.to_dict() for component in message.components]
        if (len(message.embeds) != 1
                or _comparable_payload(message.embeds[0].to_dict()) != _comparable_payload(embed.to_dict())
                or _comparable_payload(current_components) != _comparable_payload(expected_components)):
            await message.edit(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
            summary["panels_updated"] += 1
    bot.store.set_resource("panel", key, message.id)


async def _retire_pve_bases(bot: Any, guild: discord.Guild,
                            roles: dict[str, discord.Role], summary: dict[str, int]) -> None:
    """Retain a previously managed PvE listing privately after the shop migration.

    This deliberately handles only the known legacy product. A saved ID alone
    is insufficient authority to archive a channel: its exact setup marker and
    guild must also match. History and resource IDs remain available for recovery.
    """
    key = "pve-bases"
    if key in bot.settings.products:
        return
    saved = bot.store.get_resource("channel", key)
    channel = guild.get_channel(saved) if saved else None
    if channel is None:
        return
    marker = panel_marker("channel", key)
    topic_markers = [line for line in (getattr(channel, "topic", None) or "").splitlines()
                     if line.startswith("ASA-SHOP|channel|")]
    if (not isinstance(channel, discord.TextChannel)
            or channel.guild.id != guild.id or topic_markers != [marker]):
        raise ProvisioningError(
            "L'ancien salon pve-bases ne correspond pas à son identifiant et marqueur de boutique. "
            "Il a été laissé intact ; vérifiez ce salon avant de relancer."
        )
    staff_id = bot.store.get_resource("category", "staff-only")
    category = guild.get_channel(staff_id) if staff_id else None
    if not isinstance(category, discord.CategoryChannel):
        raise ProvisioningError(
            "La catégorie privée du staff est introuvable. Le salon pve-bases a été laissé intact."
        )
    overwrites = _overwrites(bot, guild, roles, "staff")
    name = "retired-pve-bases"
    if (channel.name != name or channel.category_id != category.id
            or channel.overwrites != overwrites):
        try:
            channel = await channel.edit(
                name=name, category=category, overwrites=overwrites,
                reason="ASA Small Tribes shop: retain legacy PvE listing privately",
            )
        except discord.Forbidden as exc:
            raise _channel_forbidden(guild, category, channel, overwrites, exc,
                                     channel_name=channel.name) from exc
    shop_name = str(bot.settings.config.get("shop_name", "ASA Shop"))
    embed = discord.Embed(
        title="RETIRED — PVE BASE SALES",
        description="This listing has been retired. This shop now serves ASA Small Tribes only. "
                    "Previous messages are retained for staff reference. "
                    "No orders can be placed from this panel.",
        color=int(str(bot.settings.config.get("accent_color", "B3202A")).lstrip("#"), 16),
    )
    embed.set_author(name=shop_name[:256])
    embed.set_footer(text=f"{shop_name[:128]} • {panel_marker('product', key)}")
    await _panel(bot, channel, key, "product", embed, None, summary)


async def sync_guild(bot: Any, guild: discord.Guild) -> dict[str, int]:
    """Create/update the configured shop. Caller serializes sync operations."""
    _preflight(guild)
    summary = {"roles_created": 0, "categories_created": 0, "channels_created": 0,
               "panels_created": 0, "panels_updated": 0}
    stage = "création / mise à jour des rôles"
    try:
        roles = await _roles(bot, guild, summary)
        # Text channel positions are guild-wide, not relative to each category.
        position = 0
        for category_position, spec in enumerate(bot.settings.structure):
            stage = f"création / mise à jour de la catégorie {spec['name']}"
            category = await _category(bot, guild, spec, category_position, roles, summary)
            for channel_spec in spec.get("channels", []):
                stage = f"création / mise à jour du salon {channel_spec['name']}"
                channel = await _channel(bot, guild, category, channel_spec, position, roles, summary)
                view = bot.tickets.central_view() if channel_spec["key"] == "open-a-ticket" else None
                embed = build_information_embed(bot.settings, channel_spec)
                stage = f"publication / mise à jour du panneau dans {channel_spec['name']}"
                await _panel(bot, channel, channel_spec["key"], "info", embed, view, summary)
                position += 1
            for product_id, product in bot.settings.products.items():
                if product.get("category") != spec["key"] or not product.get("channel"):
                    continue
                stage = f"création / mise à jour du salon {product['channel']}"
                channel = await _channel(
                    bot, guild, category,
                    {"key": product_id, "name": product["channel"], "mode": "readonly"},
                    position, roles, summary,
                )
                stage = f"publication / mise à jour du panneau dans {product['channel']}"
                await _panel(bot, channel, product_id, "product", build_product_embed(bot.settings, product_id),
                             bot.tickets.product_view(product_id), summary)
                position += 1
        stage = "archivage privé de l'ancien salon pve-bases"
        await _retire_pve_bases(bot, guild, roles, summary)
    except discord.Forbidden as exc:
        raise ProvisioningError(
            f"Discord refuse l'étape : {stage} (HTTP {exc.status}, code {exc.code}). "
            "Vérifiez les permissions du rôle portant le nom du bot et celles de la catégorie concernée, "
            "puis placez son rôle au-dessus des rôles de boutique. Relancez ensuite : les éléments déjà créés sont conservés."
        ) from exc
    except discord.HTTPException as exc:
        raise ProvisioningError(
            f"Discord ne termine pas l'étape : {stage} (HTTP {exc.status}, code {exc.code}). "
            "Corrigez la limite Discord ou le problème de connexion indiqué, puis relancez. Les éléments déjà créés sont conservés."
        ) from exc
    return summary
