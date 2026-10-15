#!/usr/bin/env python3
"""French CLI; all Discord-facing messages stay in English."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path
import sqlite3
import sys
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from shop.locking import InstanceLock
from shop.settings import ConfigurationError, Settings, load_settings
from shop.storage import Store
from shop.tickets import TicketService
from shop.presentation import build_product_embed
from shop.provisioning import sync_guild

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("asa_shop")


def invite_permissions() -> discord.Permissions:
    return discord.Permissions(view_channel=True, send_messages=True, embed_links=True,
                               attach_files=True, read_message_history=True,
                               manage_channels=True, manage_roles=True)


def validate_rendering(settings: Settings) -> None:
    for pid in settings.products:
        try:
            embed = build_product_embed(settings, pid)
        except ValueError as exc:
            raise ConfigurationError(str(exc)) from exc
        if len(embed) > 6000 or len(embed.fields) > 25:
            raise ConfigurationError(f"Le panneau {pid} dépasse les limites Discord.")
        if any(len(field.value) > 1024 or len(field.name) > 256 for field in embed.fields):
            raise ConfigurationError(f"Le panneau {pid} contient un champ trop long.")


class ShopBot(commands.Bot):
    def __init__(self, settings: Settings, store: Store, do_setup: bool):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents,
                         allowed_mentions=discord.AllowedMentions.none(), help_command=None)
        self.settings, self.store = settings, store
        self.tickets = TicketService(self)
        self.do_setup = do_setup
        self.sync_lock = asyncio.Lock()
        self.initialized = False
        self.exit_status = 0
        self.install_commands()

    def is_manager(self, interaction: discord.Interaction) -> bool:
        if (interaction.guild_id != self.settings.config["guild_id"]
                or not isinstance(interaction.user, discord.Member)):
            return False
        if interaction.user.id == interaction.guild.owner_id:
            return True
        role_ids = {self.store.get_resource("role", key)
                    for key in self.settings.config["manager_role_keys"]}
        return any(role.id in role_ids for role in interaction.user.roles)

    async def require_manager(self, interaction: discord.Interaction) -> bool:
        if self.is_manager(interaction):
            return True
        await interaction.response.send_message("Only the server owner or authorized shop managers can use this command.", ephemeral=True)
        return False

    def install_commands(self):
        @self.tree.command(name="shop_sync", description="Reload configuration, prices and shop panels.")
        @app_commands.guild_only()
        async def shop_sync(interaction: discord.Interaction):
            if not await self.require_manager(interaction):
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            if self.sync_lock.locked():
                await interaction.followup.send("A shop synchronization is already running. Please wait.", ephemeral=True)
                return
            async with self.sync_lock:
                try:
                    replacement = load_settings(ROOT, require_config=True)
                    validate_rendering(replacement)
                    if replacement.config["guild_id"] != self.settings.config["guild_id"]:
                        raise ConfigurationError("Redémarrez le bot pour changer de serveur.")
                    if replacement.data_dir != self.settings.data_dir:
                        raise ConfigurationError("Redémarrez le bot pour changer data_dir.")
                    self.settings = replacement
                    report = await sync_guild(self, interaction.guild)
                    await self.tickets.restore_views()
                    await interaction.followup.send(f"Shop synchronized. {report}", ephemeral=True)
                except (ConfigurationError, discord.HTTPException, RuntimeError, ValueError) as exc:
                    LOG.error("Synchronisation interrompue (%s).", type(exc).__name__)
                    await interaction.followup.send("Synchronization could not finish. Check the local console, configuration and bot role permissions, then retry. Existing completed steps are preserved.", ephemeral=True)
                    if not isinstance(exc, discord.HTTPException):
                        print(f"Synchronisation : {exc}", file=sys.stderr)

        @self.tree.command(name="shop_status", description="Show shop readiness and loaded catalogue size.")
        @app_commands.guild_only()
        async def shop_status(interaction: discord.Interaction):
            if not await self.require_manager(interaction):
                return
            count = len(self.settings.products)
            await interaction.response.send_message(
                f"Shop online • {count} configured products/services • SQLite persistence enabled. "
                "Stock and delivery are confirmed manually by staff. No automatic payment processing.", ephemeral=True)

        @self.tree.command(name="shop_orders", description="Show the last 10 completed orders privately to shop managers.")
        @app_commands.guild_only()
        async def shop_orders(interaction: discord.Interaction):
            if not await self.require_manager(interaction):
                return
            orders = self.store.recent_orders(10)
            lines = [f"**#{order['ticket_id']}** • {order['product_id']} • customer <@{order['customer_id']}>"
                     for order in orders if order["guild_id"] == interaction.guild_id]
            await interaction.response.send_message("\n".join(lines) or "No completed orders yet.", ephemeral=True,
                                                    allowed_mentions=discord.AllowedMentions.none())

        @self.tree.command(name="shop_announce", description="Publish a shop announcement.")
        @app_commands.guild_only()
        @app_commands.describe(text="Announcement in English (no mass mentions).")
        async def shop_announce(interaction: discord.Interaction, text: app_commands.Range[str, 1, 3500]):
            if not await self.require_manager(interaction):
                return
            await interaction.response.defer(ephemeral=True)
            channel = interaction.guild.get_channel(self.store.get_resource("channel", "announcements") or 0)
            if not isinstance(channel, discord.TextChannel):
                await interaction.followup.send("Run /shop_sync to create the announcements channel first.", ephemeral=True)
                return
            embed = discord.Embed(title=f"📢 {self.settings.config['shop_name']} — Announcement", description=text,
                                  color=int(self.settings.config["accent_color"].lstrip("#"), 16))
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            await interaction.followup.send("Announcement published.", ephemeral=True)

        @self.tree.error
        async def command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
            LOG.error("Commande Discord interrompue (%s).", type(error).__name__)
            message = "The command could not finish. Please check bot permissions and try again."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)

    async def setup_hook(self):
        if self.application_id != self.settings.config["application_id"]:
            raise ConfigurationError("application_id ne correspond pas au bot connecté. Vérifiez General Information dans Developer Portal.")
        guild = discord.Object(id=self.settings.config["guild_id"])
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    async def on_ready(self):
        if self.initialized:
            return
        self.initialized = True
        guild = self.get_guild(self.settings.config["guild_id"])
        if guild is None:
            print("Erreur : bot absent du serveur configuré. Vérifiez guild_id et le lien d'invitation.", file=sys.stderr)
            self.exit_status = 1
            await self.close()
            return
        try:
            if self.do_setup:
                print("Création / synchronisation du serveur en cours. Cela peut prendre plusieurs minutes…")
                async with self.sync_lock:
                    report = await sync_guild(self, guild)
                print(f"Synchronisation terminée : {report}")
            await self.tickets.restore_views()
            print(f"Boutique connectée : {self.settings.config['shop_name']}. Gardez cette fenêtre ouverte. Ctrl+C pour arrêter.")
        except Exception as exc:
            self.exit_status = 1
            if isinstance(exc, discord.Forbidden):
                print("Accès Discord refusé. Vérifiez les permissions et placez le rôle du bot au-dessus des rôles de boutique.", file=sys.stderr)
            elif isinstance(exc, discord.HTTPException):
                print(f"Discord a refusé la synchronisation (code {exc.status}). Relancez après avoir vérifié les limites du serveur.", file=sys.stderr)
            else:
                print(f"Démarrage interrompu : {exc}", file=sys.stderr)
            await self.close()

    async def on_member_join(self, member: discord.Member):
        if member.guild.id != self.settings.config["guild_id"]:
            return
        channel = member.guild.get_channel(self.store.get_resource("channel", "welcome") or 0)
        if isinstance(channel, discord.TextChannel):
            embed = discord.Embed(title=f"Welcome to {self.settings.config['shop_name']}!",
                                  description=f"Welcome, {discord.utils.escape_markdown(member.display_name)}! Read the rules, browse the catalogue and use a green product button or the ticket menu to contact staff.",
                                  color=int(self.settings.config["accent_color"].lstrip("#"), 16))
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    async def on_error(self, event_method, *args, **kwargs):
        # Discord's default handler includes tracebacks; keep secrets and message contents out of logs.
        LOG.error("Événement %s interrompu. Vérifiez les permissions et la connexion Discord.", event_method)


def backup_database(settings: Settings) -> Path:
    source = settings.data_dir / "shop.sqlite3"
    if not source.exists():
        raise ConfigurationError("Aucune base à sauvegarder. Démarrez d'abord le bot.")
    destination = settings.data_dir / "backups" / f"shop-{datetime.now(timezone.utc):%Y%m%d-%H%M%S-%f}.sqlite3"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("La sauvegarde SQLite n'a pas passé le contrôle d'intégrité.")
    return destination


async def run_bot(settings: Settings, token: str, do_setup: bool) -> int:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    lock = InstanceLock(settings.data_dir / "bot.lock")
    store = None
    try:
        store = Store(settings.data_dir / "shop.sqlite3")
        bound_guild = store.get_resource("binding", "guild")
        if bound_guild and bound_guild != settings.config["guild_id"]:
            raise ConfigurationError("Ce dossier data appartient à un autre serveur. Choisissez un nouveau data_dir pour ce serveur.")
        store.set_resource("binding", "guild", settings.config["guild_id"])
        async with ShopBot(settings, store, do_setup) as bot:
            await bot.start(token)
            return bot.exit_status
    finally:
        if store is not None:
            store.close()
        lock.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Installation et démarrage de votre boutique Discord ASA.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Vérifier tous les fichiers et panneaux sans se connecter à Discord.")
    mode.add_argument("--setup", action="store_true", help="Créer/synchroniser la boutique puis laisser le bot en ligne.")
    mode.add_argument("--invite-url", action="store_true", help="Afficher le lien d'invitation du bot, sans Administrator.")
    mode.add_argument("--backup", action="store_true", help="Sauvegarder la base SQLite de manière cohérente, même si le bot tourne.")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(ROOT, require_config=not args.check)
        validate_rendering(settings)
        if args.check:
            print(f"Configuration valide : {len(settings.structure)} catégories, {len(settings.products)} produits/services. Panneaux dans les limites Discord.")
            if settings.config["guild_id"] == 0:
                print("Modèle validé hors ligne. Renseignez config.json et .env avant la connexion Discord.")
            return 0
        if args.invite_url:
            print(discord.utils.oauth_url(settings.config["application_id"], permissions=invite_permissions(),
                                          scopes=("bot", "applications.commands"),
                                          guild=discord.Object(id=settings.config["guild_id"])))
            return 0
        if args.backup:
            print(f"Sauvegarde vérifiée : {backup_database(settings)}")
            return 0
        load_dotenv(ROOT / ".env", override=False)
        token = os.environ.get("DISCORD_TOKEN", "").strip()
        if not token or token in {"YOUR_BOT_TOKEN_HERE", "PASTE_YOUR_BOT_TOKEN_HERE", "COLLEZ_VOTRE_TOKEN_ICI"}:
            raise ConfigurationError("Token absent. Renseignez DISCORD_TOKEN dans .env. Ne partagez jamais ce fichier.")
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
        # Library logs never need gateway payloads or request headers in the beginner launcher.
        logging.getLogger("discord").setLevel(logging.WARNING)
        return asyncio.run(run_bot(settings, token, args.setup))
    except ConfigurationError as exc:
        print(f"Configuration : {exc}", file=sys.stderr)
        return 2
    except discord.LoginFailure:
        print("Token Discord invalide. Réinitialisez-le dans Developer Portal, puis mettez .env à jour.", file=sys.stderr)
        return 3
    except discord.PrivilegedIntentsRequired:
        print("Activez Server Members Intent et Message Content Intent dans Developer Portal > Bot.", file=sys.stderr)
        return 4
    except discord.Forbidden:
        print("Accès Discord refusé : vérifiez l'invitation, guild_id et les permissions du bot.", file=sys.stderr)
        return 5
    except (discord.HTTPException, discord.ConnectionClosed, OSError) as exc:
        print(f"Connexion ou accès impossible ({type(exc).__name__}). Vérifiez le réseau, Discord et l'accès au dossier.", file=sys.stderr)
        return 6
    except RuntimeError as exc:
        print(f"Démarrage : {exc}", file=sys.stderr)
        return 7
    except sqlite3.DatabaseError:
        print("Base SQLite inaccessible ou endommagée. Conservez data et restaurez une sauvegarde vérifiée avant de relancer.", file=sys.stderr)
        return 8
    except KeyboardInterrupt:
        print("Bot arrêté. Les données sont conservées.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
