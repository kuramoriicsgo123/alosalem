"""Persistent private tickets with per-product orders and durable transcripts."""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import discord

log = logging.getLogger(__name__)
NO_MENTIONS = discord.AllowedMentions.none()

MENU_GROUPS = (
    ("GENERAL ORDERS", (
        ("General Orders", "general-orders"), ("Dedi Items", "dedi-items"),
        ("Dino Lines", "dino-lines"), ("Blueprints", "blueprints"),
        ("Structures", "structures"), ("Kits", "kits"),
    )),
    ("BOSS FIGHTS", (
        ("Master Controller", "master-controller"), ("Rockwell", "rockwell"),
        ("Manticore", "manticore"), ("Overseer", "overseer"),
        ("King Titan", "king-titan"), ("Lost Queen", "lost-queen"),
        ("Kraken", "kraken"), ("Nunatak", "nunatak"),
        ("Island Bosses", "island-bosses"), ("Ragnarok Boss", "ragnarok-boss"),
        ("Moeder", "moeder"),
    )),
    ("NOTE RUNS", (
        ("Island Note Run", "island-note-run"), ("Scorched Earth Note Run", "scorched-note-run"),
        ("Aberration Note Run", "aberration-note-run"), ("Extinction Note Run", "extinction-note-run"),
    )),
    ("BASE SERVICES", (
        ("Buy Base", "bases-for-sale"), ("Sell Base", "sell-base"),
        ("Base Advertisement", "base-advertisement"),
    )),
    ("OTHER SERVICES", (
        ("Middleman Service", "middleman-service"), ("Become a Seller", "become-a-seller"),
        ("Report a Scammer", "report-a-scammer"), ("Staff Inquiries", "staff-inquiries"),
    )),
)
MENU_NAMES = {key: label for _, options in MENU_GROUPS for label, key in options}


async def reply(interaction: discord.Interaction, content: str) -> None:
    kwargs = {"ephemeral": True, "allowed_mentions": NO_MENTIONS}
    if interaction.response.is_done():
        await interaction.followup.send(content, **kwargs)
    else:
        await interaction.response.send_message(content, **kwargs)


class SafeView(discord.ui.View):
    async def on_error(self, interaction: discord.Interaction, error: Exception,
                       item: discord.ui.Item) -> None:
        log.error("Ticket interaction failed (%s)", type(error).__name__)
        try:
            await reply(interaction, "This action could not be completed. Please contact staff; your ticket has been preserved.")
        except discord.HTTPException:
            pass


class ProductButton(discord.ui.Button):
    def __init__(self, service: "TicketService", product_id: str):
        self.service = service
        self.product_id = product_id
        product = service.bot.settings.products.get(product_id, {})
        label = product.get("button_label") or f"Buy {service.product_name(product_id)}"
        super().__init__(style=discord.ButtonStyle.success, label=str(label)[:80],
                         custom_id=f"shop:buy:{product_id}")

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.service.open(interaction, self.product_id)


class TicketSelect(discord.ui.Select):
    def __init__(self, service: "TicketService", group: str, options: tuple, row: int):
        self.service = service
        super().__init__(placeholder=group, min_values=1, max_values=1, row=row,
                         custom_id=f"shop:menu:{row}",
                         options=[discord.SelectOption(label=label, value=key) for label, key in options])

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.service.open(interaction, self.values[0])


class OrderModal(discord.ui.Modal):
    def __init__(self, service: "TicketService", product_id: str):
        super().__init__(title="Order / service details", timeout=300,
                         custom_id=f"shop:order:{product_id}")
        self.service, self.product_id = service, product_id
        self.quantity = discord.ui.TextInput(label="Quantity / package / difficulty", max_length=100,
                                            placeholder="Example: 5 Dedis, Alpha, 1 breeding pair", required=False)
        self.server = discord.ui.TextInput(label="ARK map and server type", max_length=200,
                                          placeholder="Official 1x / Small Tribes / PvE + map", required=False)
        self.details = discord.ui.TextInput(label="Order details / questions", style=discord.TextStyle.paragraph,
                                           max_length=1500, required=False,
                                           placeholder="Describe your request. Never send passwords or payment card details.")
        self.add_item(self.quantity)
        self.add_item(self.server)
        self.add_item(self.details)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.service.create_ticket(interaction, self.product_id,
                                         str(self.quantity.value).strip() or "To be confirmed",
                                         str(self.server.value).strip() or "To be confirmed",
                                         str(self.details.value).strip() or "No additional details provided.")

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.error("Ticket form failed (%s)", type(error).__name__)
        await reply(interaction, "The ticket could not be created. Please contact staff.")


class ControlButton(discord.ui.Button):
    def __init__(self, service: "TicketService", ticket_id: int, action: str,
                 label: str, style: discord.ButtonStyle):
        self.service, self.ticket_id, self.action = service, ticket_id, action
        super().__init__(label=label, style=style, custom_id=f"shop:ticket:{ticket_id}:{action}")

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.service.control(interaction, self.ticket_id, self.action)


class CloseConfirmation(SafeView):
    def __init__(self, service: "TicketService", ticket_id: int, actor_id: int):
        super().__init__(timeout=60)
        self.service, self.ticket_id, self.actor_id = service, ticket_id, actor_id

    @discord.ui.button(label="Confirm close", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.actor_id:
            await reply(interaction, "Only the person who requested this confirmation may use it.")
            return
        await self.service.close_ticket(interaction, self.ticket_id)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.actor_id:
            await reply(interaction, "This confirmation belongs to another member.")
            return
        await interaction.response.edit_message(content="Ticket closure cancelled.", view=None)
        self.stop()


class TicketService:
    def __init__(self, bot):
        self.bot = bot
        self.store = bot.store
        self._user_locks: dict[int, asyncio.Lock] = {}
        self._ticket_locks: dict[int, asyncio.Lock] = {}
        self._category_lock = asyncio.Lock()
        self._registered_products: set[str] = set()
        self._registered_tickets: set[int] = set()
        self._central_registered = False

    @property
    def config(self) -> dict:
        return self.bot.settings.config

    def product_name(self, product_id: str) -> str:
        product = self.bot.settings.products.get(product_id, {})
        return str(product.get("name") or product.get("title") or MENU_NAMES.get(product_id, product_id))

    def product_view(self, product_id: str) -> discord.ui.View:
        if len(f"shop:order:{product_id}") > 100:
            raise ValueError("Product ID exceeds Discord custom_id limit")
        view = SafeView(timeout=None)
        view.add_item(ProductButton(self, product_id))
        return view

    def central_view(self) -> discord.ui.View:
        view = SafeView(timeout=None)
        for row, (name, options) in enumerate(MENU_GROUPS):
            view.add_item(TicketSelect(self, name, options, row))
        return view

    def control_view(self, ticket_id: int) -> discord.ui.View:
        view = SafeView(timeout=None)
        for action, label, style in (
            ("claim", "Claim order", discord.ButtonStyle.primary),
            ("complete", "Mark completed", discord.ButtonStyle.success),
            ("close", "Close ticket", discord.ButtonStyle.danger),
        ):
            view.add_item(ControlButton(self, ticket_id, action, label, style))
        return view

    def _valid_guild(self, interaction: discord.Interaction) -> bool:
        return (interaction.guild is not None and isinstance(interaction.user, discord.Member)
                and interaction.guild.id == int(self.config["guild_id"]))

    def _staff_keys(self, product_id: str) -> list[str]:
        if product_id == "report-a-scammer":
            # Sellers must not gain access to reports about sellers.
            return [key for key in self.config.get("sensitive_ticket_role_keys", ["owner", "admin", "moderator"])
                    if key in {"owner", "admin", "moderator"}]
        return list(self.config.get("staff_role_keys", ["owner", "admin", "moderator", "seller"]))

    def staff_roles(self, guild: discord.Guild, product_id: str) -> list[discord.Role]:
        result = []
        for key in self._staff_keys(product_id):
            role_id = self.store.get_resource("role", key)
            role = guild.get_role(role_id) if role_id else None
            if role is not None and not role.is_default():
                result.append(role)
        return result

    def is_staff(self, member: discord.Member, product_id: str) -> bool:
        if member.id == member.guild.owner_id:
            return True
        allowed = {role.id for role in self.staff_roles(member.guild, product_id)}
        return any(role.id in allowed for role in member.roles)

    def _overwrites(self, guild: discord.Guild, owner: discord.Member | discord.Object,
                    product_id: str, *, closed: bool = False, frozen: bool = False) -> dict:
        if guild.me is None:
            raise RuntimeError("Bot membership is not cached")
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False,
                create_public_threads=False, create_private_threads=False,
                send_messages_in_threads=False, mention_everyone=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                read_message_history=True, manage_channels=True,
                attach_files=True, embed_links=True, add_reactions=True,
                create_public_threads=True, create_private_threads=True,
                send_messages_in_threads=True, mention_everyone=True),
            owner: discord.PermissionOverwrite(view_channel=not closed, send_messages=not (closed or frozen),
                read_message_history=not closed, attach_files=not closed, embed_links=not closed,
                create_public_threads=False, create_private_threads=False,
                send_messages_in_threads=False, add_reactions=not (closed or frozen),
                mention_everyone=False),
        }
        for role in self.staff_roles(guild, product_id):
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=not (closed or frozen),
                read_message_history=True, attach_files=True, embed_links=True,
                create_public_threads=False, create_private_threads=False,
                send_messages_in_threads=False, add_reactions=not (closed or frozen), mention_everyone=False)
        return overwrites

    async def open(self, interaction: discord.Interaction, product_id: str) -> None:
        if not self._valid_guild(interaction):
            await reply(interaction, "This shop is only available in its configured server.")
            return
        if product_id not in self.bot.settings.products and product_id not in MENU_NAMES:
            await reply(interaction, "This product is no longer listed. Please contact staff.")
            return
        existing = self.store.active_ticket(interaction.guild.id, interaction.user.id, product_id)
        if existing and existing["channel_id"] and interaction.guild.get_channel(existing["channel_id"]):
            await reply(interaction, f"You already have a ticket for this request: <#{existing['channel_id']}>.")
            return
        await interaction.response.send_modal(OrderModal(self, product_id))

    async def _category(self, guild: discord.Guild) -> discord.CategoryChannel:
        capacity = max(1, min(int(self.config.get("ticket_category_capacity", 45)), 49))
        for index in range(1, 21):
            key = "tickets" if index == 1 else f"tickets-overflow-{index}"
            resource_id = self.store.get_resource("category", key)
            category = guild.get_channel(resource_id) if resource_id else None
            if isinstance(category, discord.CategoryChannel):
                if len(category.channels) < capacity:
                    return category
                continue
            # New categories are also private; each ticket gets explicit overwrites.
            category = await guild.create_category(
                f"🎫 PRIVATE TICKETS {index:02d}",
                overwrites={guild.default_role: discord.PermissionOverwrite(view_channel=False),
                            guild.me: discord.PermissionOverwrite(view_channel=True, manage_channels=True)},
                reason="ASA shop ticket capacity",
            )
            self.store.set_resource("category", key, category.id)
            return category
        raise RuntimeError("Ticket category capacity exhausted; archive old channels")

    @staticmethod
    def _marker(ticket: dict) -> str:
        return f"ASA Shop ticket #{ticket['id']} | owner={ticket['user_id']} | product={ticket['product_id']}"

    async def _reconcile(self, guild: discord.Guild, ticket: dict,
                         channels: list | None = None) -> dict | None:
        """Only mark absent channels after a successful authoritative REST fetch."""
        supplied_snapshot = channels is not None
        if channels is None:
            channels = await guild.fetch_channels()
        matches = [channel for channel in channels if isinstance(channel, discord.TextChannel)
                   and (channel.id == ticket["channel_id"] or channel.topic == self._marker(ticket))]
        # A startup snapshot may predate another callback's channel creation.
        if not matches and supplied_snapshot:
            return await self._reconcile(guild, ticket)
        if len(matches) > 1:
            raise RuntimeError(f"Several channels identify ticket #{ticket['id']}; ask staff to inspect them")
        channel = matches[0] if matches else None
        if channel is None:
            self.store.update_ticket(ticket["id"], status="failed" if ticket["status"] == "creating" else "closed",
                                     closed_at=time.time())
            return None
        if channel.topic != self._marker(ticket):
            raise RuntimeError(f"Ticket #{ticket['id']} channel marker changed; ask staff to inspect it")
        # Restore privacy on every restart/sync, including a crash during closing.
        # A typed Object also works when the client has left the guild/cache.
        owner = guild.get_member(ticket["user_id"]) or discord.Object(id=ticket["user_id"], type=discord.Member)
        expected = self._overwrites(guild, owner, ticket["product_id"])
        if channel.overwrites != expected or ticket["status"] == "closing":
            await channel.edit(overwrites=expected, name=f"ticket-{ticket['id']:05d}",
                               reason="Restore private ASA ticket access after restart")
        self.store.update_ticket(ticket["id"], channel_id=channel.id, status="open")
        return self.store.get_ticket(ticket["id"])

    async def create_ticket(self, interaction: discord.Interaction, product_id: str,
                            quantity: str, server: str, details: str) -> None:
        if not self._valid_guild(interaction):
            await reply(interaction, "This shop is only available in its configured server.")
            return
        if product_id not in self.bot.settings.products and product_id not in MENU_NAMES:
            await reply(interaction, "This product is no longer listed. Please contact staff.")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild, member = interaction.guild, interaction.user
        lock = self._user_locks.setdefault(member.id, asyncio.Lock())
        async with lock:
            existing = self.store.active_ticket(guild.id, member.id, product_id)
            if existing and (existing["status"] == "creating" or guild.get_channel(existing["channel_id"] or 0) is None):
                async with self._ticket_locks.setdefault(existing["id"], asyncio.Lock()):
                    current = self.store.get_ticket(existing["id"])
                    existing = await self._reconcile(guild, current) if current["status"] != "closed" else None
            if existing:
                await reply(interaction, f"You already have a ticket for this request: <#{existing['channel_id']}>.")
                return
            # A manually deleted ticket for another product must not consume
            # the customer's open-ticket allowance indefinitely.
            for other in self.store.active_tickets(guild.id):
                if other["user_id"] == member.id and guild.get_channel(other["channel_id"] or 0) is None:
                    async with self._ticket_locks.setdefault(other["id"], asyncio.Lock()):
                        current = self.store.get_ticket(other["id"])
                        if current["status"] in {"creating", "open", "closing"}:
                            await self._reconcile(guild, current)
            if self.store.count_active(guild.id, member.id) >= int(self.config.get("max_open_tickets_per_user", 3)):
                await reply(interaction, "You have reached the open-ticket limit. Please finish or close an existing ticket first.")
                return
            last = self.store.last_created(guild.id, member.id)
            remaining = int(self.config.get("ticket_cooldown_seconds", 30)) - (time.time() - (last or 0))
            if remaining > 0:
                await reply(interaction, f"Please wait {int(remaining) + 1} seconds before opening another ticket.")
                return
            try:
                ticket = self.store.reserve_ticket(guild_id=guild.id, user_id=member.id, product_id=product_id,
                    product_name=self.product_name(product_id), quantity=quantity[:100], server=server[:200], details=details[:1500])
            except sqlite3.IntegrityError:
                await reply(interaction, "This request already has a ticket being created. Please try again in a moment.")
                return
            channel = None
            try:
                async with self._category_lock:
                    category = await self._category(guild)
                    channel = await guild.create_text_channel(f"ticket-{ticket['id']:05d}", category=category,
                        topic=self._marker(ticket), overwrites=self._overwrites(guild, member, product_id),
                        reason="Private ASA shop order")
                    self.store.update_ticket(ticket["id"], channel_id=channel.id, status="open")
                ticket = self.store.get_ticket(ticket["id"])
                await self._send_controls(channel, ticket)
                await reply(interaction, f"Your private ticket for **{discord.utils.escape_markdown(ticket['product_name'])}** is ready: {channel.mention}")
            except Exception as error:
                log.error("Ticket %s creation interrupted (%s)", ticket["id"], type(error).__name__)
                if channel is not None:
                    self.store.update_ticket(ticket["id"], channel_id=channel.id, status="open")
                    await reply(interaction, f"Your ticket was created: {channel.mention}. Staff should refresh the shop to restore its controls.")
                else:
                    # Keep the reservation: a timed-out API request may still have created a channel.
                    await reply(interaction, "Discord could not finish creating this ticket. Please retry shortly; existing channels will be checked before another is created.")

    async def _send_controls(self, channel: discord.TextChannel, ticket: dict) -> None:
        commercial = self.bot.settings.products.get(ticket["product_id"], {}).get("commercial", True)
        description = "Welcome! Our staff will review your request as soon as possible."
        if commercial:
            description += "\nConfirm availability and the fixed price with staff before paying.\n**All prices are fixed and non-negotiable.**"
        else:
            description += "\nDescribe your request below. No purchase is required."
        embed = discord.Embed(title=f"🎟️ {ticket['product_name']}"[:256], color=0xB3262D, description=description)
        embed.add_field(name="Customer", value=f"<@{ticket['user_id']}>", inline=False)
        embed.add_field(name="Product / service", value=discord.utils.escape_markdown(ticket["product_name"])[:1024], inline=False)
        embed.add_field(name="Quantity / package / difficulty", value=discord.utils.escape_markdown(ticket["quantity"])[:1024], inline=False)
        embed.add_field(name="ARK map and server type", value=discord.utils.escape_markdown(ticket["server"])[:1024], inline=False)
        details = ticket["details"]
        for offset in range(0, len(details), 1000):
            embed.add_field(name="Details" if offset == 0 else "Details (continued)",
                            value=discord.utils.escape_markdown(details[offset:offset + 1000])[:1024], inline=False)
        embed.set_footer(text=f"Order reference #{ticket['id']} • Private staff support • Never share account passwords")
        message = await channel.send(embed=embed, view=self.control_view(ticket["id"]), allowed_mentions=NO_MENTIONS)
        self.store.update_ticket(ticket["id"], control_message_id=message.id)
        self._registered_tickets.add(ticket["id"])

    async def restore_views(self) -> None:
        for product_id in self.bot.settings.products:
            if product_id not in self._registered_products:
                self.bot.add_view(self.product_view(product_id))
                self._registered_products.add(product_id)
        if not self._central_registered:
            self.bot.add_view(self.central_view())
            self._central_registered = True
        guild = self.bot.get_guild(int(self.config["guild_id"]))
        if guild is None:
            return  # Call again from on_ready when the guild cache is available.
        tickets = self.store.active_tickets(guild.id)
        if not tickets:
            return
        channels = await guild.fetch_channels()
        for ticket in tickets:
            async with self._user_locks.setdefault(ticket["user_id"], asyncio.Lock()):
                async with self._ticket_locks.setdefault(ticket["id"], asyncio.Lock()):
                    # Creation/closure may have finished while we waited for a lock.
                    ticket = self.store.get_ticket(ticket["id"])
                    if ticket["status"] not in {"creating", "open", "closing"}:
                        continue
                    ticket = await self._reconcile(guild, ticket, channels)
                    if not ticket:
                        continue
                    channel = next((item for item in channels if item.id == ticket["channel_id"]), None)
                    if channel is None:
                        channel = await guild.fetch_channel(ticket["channel_id"])
                    if not isinstance(channel, discord.TextChannel):
                        continue
                    message = await self._find_controls(channel, ticket)
                    if message is None:
                        await self._send_controls(channel, ticket)
                    elif ticket["id"] not in self._registered_tickets:
                        self.bot.add_view(self.control_view(ticket["id"]), message_id=message.id)
                        self._registered_tickets.add(ticket["id"])

    async def _find_controls(self, channel: discord.TextChannel, ticket: dict):
        """Recover a welcome message sent just before a local commit was lost."""
        marker = f"Order reference #{ticket['id']} • Private staff support • Never share account passwords"
        def matches(message):
            return message.author.id == self.bot.user.id and any(
                embed.footer.text == marker for embed in message.embeds)
        if ticket["control_message_id"]:
            try:
                message = await channel.fetch_message(ticket["control_message_id"])
            except discord.NotFound:
                pass
            else:
                if not matches(message):
                    raise RuntimeError(f"Saved controls do not identify ticket #{ticket['id']}")
                return message
        async for message in channel.history(limit=None, oldest_first=True):
            if matches(message):
                self.store.update_ticket(ticket["id"], control_message_id=message.id)
                return message
        return None

    async def _authorize(self, interaction: discord.Interaction, ticket_id: int,
                         staff_only: bool = False) -> dict | None:
        if not self._valid_guild(interaction):
            await reply(interaction, "This action is not available here.")
            return None
        ticket = self.store.get_ticket(ticket_id)
        if (ticket is None or ticket["guild_id"] != interaction.guild.id
                or ticket["channel_id"] != interaction.channel_id or ticket["status"] != "open"):
            await reply(interaction, "This ticket is no longer open or these controls do not belong to this channel.")
            return None
        staff = self.is_staff(interaction.user, ticket["product_id"])
        if not staff and (staff_only or ticket["user_id"] != interaction.user.id):
            await reply(interaction, "You do not have permission to perform this ticket action.")
            return None
        return ticket

    async def control(self, interaction: discord.Interaction, ticket_id: int, action: str) -> None:
        lock = self._ticket_locks.setdefault(ticket_id, asyncio.Lock())
        async with lock:
            ticket = await self._authorize(interaction, ticket_id, staff_only=action != "close")
            if ticket is None:
                return
            if action == "close":
                await interaction.response.send_message(
                    "Close this ticket? A transcript will be saved and the channel will be archived for staff. You will lose access.",
                    view=CloseConfirmation(self, ticket_id, interaction.user.id), ephemeral=True,
                    allowed_mentions=NO_MENTIONS)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            if action == "claim":
                if not self.store.claim_ticket(ticket_id, interaction.user.id):
                    assigned = self.store.get_ticket(ticket_id)["claimed_by"]
                    await reply(interaction, f"This ticket is already assigned to <@{assigned}>.")
                    return
                await interaction.channel.send(f"Staff member <@{interaction.user.id}> is handling order #{ticket_id}.", allowed_mentions=NO_MENTIONS)
                await reply(interaction, "Order assigned to you.")
            elif action == "complete":
                if not self.store.complete_ticket(ticket_id, interaction.user.id):
                    await reply(interaction, "This order has already been marked completed.")
                    return
                await interaction.channel.send(f"✅ Order #{ticket_id} has been marked completed by <@{interaction.user.id}>. Thank you!", allowed_mentions=NO_MENTIONS)
                await reply(interaction, "Order completed and saved in the order database. The ticket remains open until closed.")

    def _safe_log_channel(self, guild: discord.Guild, product_id: str,
                          channel=None) -> discord.TextChannel | None:
        if channel is None:
            channel_id = self.store.get_resource("channel", "ticket-logs")
            channel = guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return None
        if channel.overwrites_for(guild.default_role).view_channel is not False:
            return None
        staff_ids = {role.id for role in self.staff_roles(guild, product_id)}
        for target, overwrite in channel.overwrites.items():
            if overwrite.view_channel is not True:
                continue
            if isinstance(target, discord.Role):
                if target.id not in staff_ids:
                    return None
            elif isinstance(target, discord.Member):
                if target.id not in {guild.me.id, guild.owner_id}:
                    return None
            elif isinstance(target, discord.Object):
                # Discord returns typed Objects when an overwrite target is not
                # cached. Unknown members/roles must never expose transcripts.
                allowed = staff_ids if target.type is discord.Role else {guild.me.id, guild.owner_id}
                if target.id not in allowed:
                    return None
            else:
                return None
        return channel

    async def _transcript(self, channel: discord.TextChannel, ticket: dict) -> Path:
        if not self.bot.intents.message_content:
            raise RuntimeError("Enable Message Content intent before exporting transcripts")
        limit = max(1, int(self.config.get("transcript_limit", 10000)))
        lines = [f"ASA Shop transcript — ticket #{ticket['id']}",
                 f"Guild: {ticket['guild_id']} | Channel: {channel.id}",
                 f"Customer: {ticket['user_id']} | Product: {ticket['product_name']}",
                 "Attachments are recorded as URLs; files are not downloaded.\n"]
        count = 0
        async for message in channel.history(limit=limit + 1, oldest_first=True):
            count += 1
            if count > limit:
                raise RuntimeError(f"Ticket exceeds transcript_limit ({limit}); increase it and retry")
            lines.append(f"[{message.created_at.isoformat()}] {message.author} ({message.author.id}) — message {message.id}")
            lines.append(message.content or "[No text content]")
            for embed in message.embeds:
                if embed.title:
                    lines.append(f"[Embed] {embed.title}")
                if embed.description:
                    lines.append(embed.description)
                for field in embed.fields:
                    lines.append(f"{field.name}: {field.value}")
                for label, url in (("Embed URL", embed.url), ("Image", embed.image.url),
                                   ("Thumbnail", embed.thumbnail.url)):
                    if url:
                        lines.append(f"[{label}] {url}")
            for attachment in message.attachments:
                lines.append(f"[Attachment] {attachment.filename}: {attachment.url}")
            if message.edited_at:
                lines.append(f"[Last edited: {message.edited_at.isoformat()}]")
            lines.append("")
        data_dir = Path(self.config.get("data_dir", "data"))
        if not data_dir.is_absolute():
            data_dir = self.bot.settings.root / data_dir
        directory = data_dir / "transcripts"
        directory.mkdir(parents=True, exist_ok=True)
        try:
            directory.chmod(0o700)
        except OSError:
            pass
        path = directory / f"ticket-{ticket['id']:05d}.txt"
        temporary = path.with_suffix(".tmp")
        text = "\n".join(lines)
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        temporary.replace(path)
        return path

    async def close_ticket(self, interaction: discord.Interaction, ticket_id: int) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        lock = self._ticket_locks.setdefault(ticket_id, asyncio.Lock())
        async with lock:
            ticket = await self._authorize(interaction, ticket_id)
            if ticket is None:
                return
            channel = interaction.channel
            if not isinstance(channel, discord.TextChannel):
                await reply(interaction, "Ticket closure requires a text channel.")
                return
            owner = interaction.guild.get_member(ticket["user_id"]) or discord.Object(
                id=ticket["user_id"], type=discord.Member)
            self.store.update_ticket(ticket_id, status="closing")
            try:
                # Freeze customer/staff writes before reading history, so the
                # archive includes every message accepted before closure.
                await channel.edit(overwrites=self._overwrites(
                    interaction.guild, owner, ticket["product_id"], frozen=True),
                    reason=f"Freeze ASA shop ticket #{ticket_id} for transcript")
                path = await self._transcript(channel, ticket)
                self.store.update_ticket(ticket_id, transcript_path=str(path))
                await channel.edit(name=f"closed-{ticket_id:05d}",
                    overwrites=self._overwrites(interaction.guild, owner, ticket["product_id"], closed=True),
                    reason=f"Archived ASA shop ticket #{ticket_id}")
                self.store.update_ticket(ticket_id, status="closed", closed_at=time.time())
            except Exception as error:
                # Do not report an open ticket while its client remains locked
                # out. If restoring access fails, keep 'closing' for restart/sync
                # reconciliation, retaining the complete channel and database.
                try:
                    await channel.edit(overwrites=self._overwrites(
                        interaction.guild, owner, ticket["product_id"]),
                        name=f"ticket-{ticket_id:05d}", reason="Restore ticket after interrupted closure")
                except Exception:
                    log.error("Ticket %s access recovery pending; restart or synchronize", ticket_id)
                else:
                    self.store.update_ticket(ticket_id, status="open", transcript_path=None)
                log.error("Ticket %s closure failed (%s)", ticket_id, type(error).__name__)
                explanation = str(error) if isinstance(error, RuntimeError) else "Check the bot's channel permissions and local disk access."
                await reply(interaction, f"The ticket was preserved because closure could not finish. {explanation}")
                return

            # These are best-effort notifications after the durable close.
            # An expired interaction or failed upload must never reopen a ticket.
            uploaded = False
            log_channel = None
            log_id = self.store.get_resource("channel", "ticket-logs")
            if log_id:
                try:
                    fresh_channel = await interaction.guild.fetch_channel(log_id)
                    log_channel = self._safe_log_channel(interaction.guild, ticket["product_id"], fresh_channel)
                except discord.HTTPException:
                    log.warning("Ticket %s transcript kept locally; log permissions unavailable", ticket_id)
            if log_channel and path.stat().st_size < interaction.guild.filesize_limit:
                try:
                    with discord.File(path, filename=path.name) as attachment:
                        await log_channel.send(
                            f"Transcript for order #{ticket_id} • closed by <@{interaction.user.id}>.",
                            file=attachment, allowed_mentions=NO_MENTIONS)
                    uploaded = True
                except (discord.HTTPException, OSError):
                    log.warning("Ticket %s transcript kept locally; staff log upload unavailable", ticket_id)
            try:
                await channel.send("🔒 This ticket is now closed. Its transcript has been saved for staff.",
                                   allowed_mentions=NO_MENTIONS)
                if ticket["control_message_id"]:
                    message = await channel.fetch_message(ticket["control_message_id"])
                    await message.edit(view=None)
            except discord.HTTPException:
                pass  # Stale controls still reject actions against closed records.
            note = "" if uploaded else " Staff can retrieve the transcript from the private local data folder."
            await reply(interaction, "Ticket closed and archived. The transcript was saved." + note)
