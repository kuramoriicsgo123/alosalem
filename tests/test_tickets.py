"""Offline regressions for ticket privacy, restart recovery and durable orders."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock

import discord

from shop.storage import Store
from shop.tickets import TicketService, MENU_GROUPS


def http_error(cls=discord.HTTPException, status=503):
    return cls(SimpleNamespace(status=status, reason="Test failure"), "Test failure")


def role(role_id):
    value = MagicMock(spec=discord.Role)
    value.id = role_id
    value.is_default.return_value = False
    return value


def member(member_id, guild, roles=()):
    value = MagicMock(spec=discord.Member)
    value.id, value.guild, value.roles = member_id, guild, list(roles)
    return value


def interaction(guild, user, channel=None):
    value = SimpleNamespace(guild=guild, user=user, channel=channel,
                            channel_id=channel.id if channel else 0)
    value.response = MagicMock()
    value.response.is_done.return_value = True
    value.response.defer = AsyncMock()
    value.response.send_modal = AsyncMock()
    value.response.send_message = AsyncMock()
    value.followup = SimpleNamespace(send=AsyncMock())
    return value


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "shop.sqlite3"
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def reserve(self, product="rex-lines"):
        return self.store.reserve_ticket(guild_id=1, user_id=2, product_id=product,
            product_name="Rex Lines", quantity="1 breeding pair", server="PvE", details="Blue colors")

    def test_ids_orders_and_claim_survive_reopening(self):
        self.store.set_resource("channel", "open-a-ticket", 80)
        ticket = self.reserve()
        self.store.update_ticket(ticket["id"], status="open", channel_id=90)
        self.assertTrue(self.store.claim_ticket(ticket["id"], 5))
        self.assertFalse(self.store.claim_ticket(ticket["id"], 6))
        self.assertTrue(self.store.complete_ticket(ticket["id"], 5))
        self.assertFalse(self.store.complete_ticket(ticket["id"], 6))
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.get_resource("channel", "open-a-ticket"), 80)
        self.assertEqual(self.store.ticket_by_channel(90)["claimed_by"], 5)
        self.assertEqual(len(self.store.recent_orders()), 1)
        self.assertEqual(self.store.recent_orders()[0]["completed_by"], 5)
        self.assertEqual(self.store.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_database_prevents_duplicates_but_allows_new_order_after_closure(self):
        ticket = self.reserve()
        with self.assertRaises(sqlite3.IntegrityError):
            self.reserve()
        self.store.update_ticket(ticket["id"], status="closed")
        self.assertNotEqual(self.reserve()["id"], ticket["id"])

    def test_closed_ticket_cannot_be_claimed_or_completed(self):
        ticket = self.reserve()
        self.store.update_ticket(ticket["id"], status="closed")
        self.assertFalse(self.store.claim_ticket(ticket["id"], 5))
        self.assertFalse(self.store.complete_ticket(ticket["id"], 5))
        self.assertEqual(self.store.recent_orders(), [])

    def test_second_connection_cannot_complete_order_twice(self):
        ticket = self.reserve()
        self.store.update_ticket(ticket["id"], status="open")
        other = Store(self.path)
        try:
            self.assertTrue(other.complete_ticket(ticket["id"], 5))
            self.assertFalse(self.store.complete_ticket(ticket["id"], 6))
        finally:
            other.close()


class TicketTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "data" / "shop.sqlite3")
        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id, self.guild.owner_id, self.guild.filesize_limit = 1, 100, 8_000_000
        self.guild.default_role = role(1)
        self.roles = {key: role(index) for index, key in enumerate(
            ["owner", "admin", "moderator", "seller"], start=10)}
        for key, value in self.roles.items():
            self.store.set_resource("role", key, value.id)
        self.guild.get_role.side_effect = lambda role_id: next(
            (value for value in self.roles.values() if value.id == role_id), None)
        self.guild.me = member(900, self.guild)
        self.customer = member(101, self.guild)
        self.staff = member(102, self.guild, [self.roles["moderator"]])
        self.seller = member(103, self.guild, [self.roles["seller"]])
        members = {value.id: value for value in [self.customer, self.staff, self.seller, self.guild.me]}
        self.guild.get_member.side_effect = members.get
        self.channels = []
        self.next_channel_id = 200
        self.guild.get_channel.side_effect = lambda channel_id: next(
            (channel for channel in self.channels if channel.id == channel_id), None)
        self.guild.fetch_channels = AsyncMock(side_effect=lambda: list(self.channels))
        self.guild.fetch_channel = AsyncMock(side_effect=lambda channel_id: self.guild.get_channel(channel_id))
        self.config = {"guild_id": 1, "data_dir": "data", "ticket_cooldown_seconds": 30,
                       "max_open_tickets_per_user": 3, "transcript_limit": 100,
                       "staff_role_keys": ["owner", "admin", "moderator", "seller"]}
        self.bot = SimpleNamespace(
            settings=SimpleNamespace(config=self.config, root=self.root,
                products={"rex-lines": {"name": "Rex Lines"}, "metal-ingots": {"name": "Metal Ingots"}}),
            store=self.store, user=SimpleNamespace(id=900),
            intents=SimpleNamespace(message_content=True), add_view=MagicMock(),
            get_guild=lambda guild_id: self.guild if guild_id == 1 else None)
        self.service = TicketService(self.bot)
        self.category = MagicMock(spec=discord.CategoryChannel)
        self.category.id, self.category.channels = 600, []
        self.service._category = AsyncMock(return_value=self.category)
        self.guild.create_text_channel = AsyncMock(side_effect=self.create_channel)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def create_channel(self, name, **kwargs):
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = self.next_channel_id
        self.next_channel_id += 1
        channel.name = name
        channel.mention = f"<#{channel.id}>"
        channel.topic = kwargs.get("topic")
        channel.overwrites = kwargs.get("overwrites", {})
        channel.overwrites_for.side_effect = lambda target: channel.overwrites.get(target, discord.PermissionOverwrite())
        channel.messages = []

        async def history(**kwargs):
            limit = kwargs.get("limit")
            for message in channel.messages[:limit]:
                yield message

        def send(*args, **kwargs):
            message = SimpleNamespace(id=1000 + len(channel.messages),
                author=SimpleNamespace(id=900), content=args[0] if args else "",
                embeds=[kwargs["embed"]] if "embed" in kwargs else [],
                attachments=[], created_at=datetime.now(timezone.utc), edited_at=None,
                edit=AsyncMock())
            channel.messages.append(message)
            return message

        async def edit(**kwargs):
            for key, value in kwargs.items():
                if key != "reason":
                    setattr(channel, key, value)
            return channel

        async def fetch_message(message_id):
            for message in channel.messages:
                if message.id == message_id:
                    return message
            raise http_error(discord.NotFound, 404)

        channel.history = history
        channel.send = AsyncMock(side_effect=send)
        channel.edit = AsyncMock(side_effect=edit)
        channel.fetch_message = AsyncMock(side_effect=fetch_message)
        self.channels.append(channel)
        return channel

    def ticket(self, product="rex-lines", status="open", with_channel=True):
        ticket = self.store.reserve_ticket(guild_id=1, user_id=self.customer.id,
            product_id=product, product_name=self.service.product_name(product),
            quantity="5", server="PvE", details="No sensitive payment data.")
        channel = None
        if with_channel:
            channel = self.create_channel("ticket", topic=self.service._marker(ticket),
                overwrites=self.service._overwrites(self.guild, self.customer, product))
            self.store.update_ticket(ticket["id"], channel_id=channel.id, status=status)
        else:
            self.store.update_ticket(ticket["id"], status=status)
        return self.store.get_ticket(ticket["id"]), channel

    async def test_real_green_persistent_button_routes_exact_product(self):
        view = self.service.product_view("rex-lines")
        self.assertTrue(view.is_persistent())
        button = view.children[0]
        self.assertEqual(button.style, discord.ButtonStyle.success)
        self.assertEqual(button.custom_id, "shop:buy:rex-lines")
        self.service.open = AsyncMock()
        request = interaction(self.guild, self.customer)
        await button.callback(request)
        self.service.open.assert_awaited_once_with(request, "rex-lines")
        central = self.service.central_view()
        self.assertTrue(central.is_persistent())
        self.assertEqual(len(central.children), 5)
        self.assertTrue(all(len(menu.options) <= 25 for menu in central.children))
        self.assertEqual([menu.row for menu in central.children], list(range(len(MENU_GROUPS))))

    async def test_report_private_and_seller_not_staff(self):
        self.config["sensitive_ticket_role_keys"] = ["owner", "admin", "moderator", "seller", "vip"]
        overwrites = self.service._overwrites(self.guild, self.customer, "report-a-scammer")
        self.assertFalse(overwrites[self.guild.default_role].view_channel)
        self.assertTrue(overwrites[self.customer].view_channel)
        self.assertFalse(overwrites[self.customer].create_private_threads)
        self.assertNotIn(self.roles["seller"], overwrites)
        self.assertIsNone(overwrites[self.guild.me].manage_messages)
        self.assertTrue(self.service.is_staff(self.staff, "report-a-scammer"))
        self.assertFalse(self.service.is_staff(self.seller, "report-a-scammer"))

    async def test_unsafe_logs_with_seller_or_uncached_member_are_rejected(self):
        channel = self.create_channel("logs", overwrites={
            self.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            self.guild.me: discord.PermissionOverwrite(view_channel=True),
            self.roles["seller"]: discord.PermissionOverwrite(view_channel=True)})
        self.store.set_resource("channel", "ticket-logs", channel.id)
        self.assertIsNone(self.service._safe_log_channel(self.guild, "report-a-scammer"))
        self.assertIs(self.service._safe_log_channel(self.guild, "rex-lines"), channel)
        channel.overwrites[discord.Object(id=9999, type=discord.Member)] = discord.PermissionOverwrite(view_channel=True)
        self.assertIsNone(self.service._safe_log_channel(self.guild, "rex-lines"))

    async def test_simultaneous_clicks_create_only_one_private_ticket(self):
        first, second = interaction(self.guild, self.customer), interaction(self.guild, self.customer)
        await asyncio.gather(*(self.service.create_ticket(request, "rex-lines", "1", "PvE", "Blue")
                               for request in [first, second]))
        self.guild.create_text_channel.assert_awaited_once()
        self.assertEqual(self.store.count_active(1, self.customer.id), 1)
        self.assertIn("already have a ticket", second.followup.send.call_args.args[0])
        channel = self.channels[0]
        self.assertFalse(channel.overwrites[self.guild.default_role].view_channel)
        self.assertTrue(channel.overwrites[self.customer].view_channel)

    async def test_cooldown_and_ticket_limit_cover_different_products(self):
        await self.service.create_ticket(interaction(self.guild, self.customer), "rex-lines", "1", "PvE", "Blue")
        request = interaction(self.guild, self.customer)
        await self.service.create_ticket(request, "metal-ingots", "1", "PvE", "")
        self.assertIn("Please wait", request.followup.send.call_args.args[0])
        self.config["max_open_tickets_per_user"] = 1
        request = interaction(self.guild, self.customer)
        await self.service.create_ticket(request, "metal-ingots", "1", "PvE", "")
        self.assertIn("open-ticket limit", request.followup.send.call_args.args[0])
        self.guild.create_text_channel.assert_awaited_once()

    async def test_only_customer_or_allowed_staff_can_close_in_original_channel(self):
        ticket, channel = self.ticket("report-a-scammer")
        for actor in [member(999, self.guild), self.seller]:
            self.assertIsNone(await self.service._authorize(interaction(self.guild, actor, channel), ticket["id"]))
        self.assertIsNone(await self.service._authorize(interaction(self.guild, self.customer, channel), ticket["id"], staff_only=True))
        elsewhere = self.create_channel("unrelated")
        self.assertIsNone(await self.service._authorize(interaction(self.guild, self.staff, elsewhere), ticket["id"]))
        self.assertIsNotNone(await self.service._authorize(interaction(self.guild, self.staff, channel), ticket["id"], staff_only=True))

    async def test_deleted_channel_is_reconciled_but_rest_failure_never_discards_ticket(self):
        ticket, channel = self.ticket()
        self.channels.clear()
        self.guild.fetch_channels.side_effect = http_error()
        with self.assertRaises(discord.HTTPException):
            await self.service._reconcile(self.guild, ticket)
        self.assertEqual(self.store.get_ticket(ticket["id"])["status"], "open")
        self.guild.fetch_channels.side_effect = lambda: []
        self.assertIsNone(await self.service._reconcile(self.guild, ticket))
        self.assertEqual(self.store.get_ticket(ticket["id"])["status"], "closed")

    async def test_missing_ticket_does_not_trap_product_button(self):
        self.ticket()
        self.channels.clear()
        request = interaction(self.guild, self.customer)
        await self.service.open(request, "rex-lines")
        request.response.send_modal.assert_awaited_once()

    async def test_deleted_other_product_ticket_does_not_consume_open_limit(self):
        ticket, _ = self.ticket()
        self.channels.clear()
        self.config["max_open_tickets_per_user"] = 1
        with self.store.db:
            self.store.db.execute("UPDATE tickets SET created_at=0 WHERE id=?", (ticket["id"],))
        await self.service.create_ticket(interaction(self.guild, self.customer), "metal-ingots", "1", "PvE", "")
        self.assertEqual(self.store.get_ticket(ticket["id"])["status"], "closed")
        self.assertEqual(self.store.count_active(1, self.customer.id), 1)
        self.guild.create_text_channel.assert_awaited_once()

    async def test_restart_repairs_interrupted_close_permissions_and_restores_views(self):
        ticket, channel = self.ticket(status="closing")
        channel.overwrites = self.service._overwrites(self.guild, self.customer, "rex-lines", closed=True)
        await self.service.restore_views()
        self.assertEqual(self.store.get_ticket(ticket["id"])["status"], "open")
        self.assertTrue(channel.overwrites[self.customer].view_channel)
        self.assertTrue(channel.overwrites[self.customer].send_messages)
        self.assertEqual(len(channel.messages), 1)
        recovered = TicketService(self.bot)
        await recovered.restore_views()
        self.assertEqual(len(channel.messages), 1)
        self.assertTrue(any(call.kwargs.get("message_id") == channel.messages[0].id
                            for call in self.bot.add_view.call_args_list))

    async def test_restart_recovers_controls_sent_before_database_commit(self):
        ticket, channel = self.ticket()
        await self.service._send_controls(channel, ticket)
        message_id = channel.messages[0].id
        self.store.update_ticket(ticket["id"], control_message_id=None)
        recovered = TicketService(self.bot)
        await recovered.restore_views()
        self.assertEqual(len(channel.messages), 1)
        self.assertEqual(self.store.get_ticket(ticket["id"])["control_message_id"], message_id)

    async def test_creation_recovered_by_marker_and_stale_snapshot_is_refetched(self):
        ticket, _ = self.ticket(status="creating", with_channel=False)
        channel = self.create_channel("ticket", topic=self.service._marker(ticket))
        recovered = await self.service._reconcile(self.guild, ticket, [])
        self.assertEqual(recovered["channel_id"], channel.id)
        self.assertEqual(recovered["status"], "open")
        self.guild.fetch_channels.assert_awaited_once()
        self.assertFalse(channel.overwrites[self.guild.default_role].view_channel)

    async def test_close_freezes_before_transcript_and_removes_customer_access(self):
        ticket, channel = self.ticket()
        await self.service._send_controls(channel, ticket)
        original = self.service._transcript

        async def checked_transcript(*args):
            self.assertFalse(channel.overwrites[self.customer].send_messages)
            self.assertTrue(channel.overwrites[self.customer].view_channel)
            return await original(*args)

        self.service._transcript = checked_transcript
        request = interaction(self.guild, self.customer, channel)
        await self.service.close_ticket(request, ticket["id"])
        saved = self.store.get_ticket(ticket["id"])
        self.assertEqual(saved["status"], "closed")
        self.assertFalse(channel.overwrites[self.customer].view_channel)
        self.assertFalse(channel.overwrites[self.roles["seller"]].send_messages)
        text = Path(saved["transcript_path"]).read_text(encoding="utf-8")
        self.assertIn("Rex Lines", text)
        self.assertIn("No sensitive payment data.", text)
        self.assertIn("message 1000", text)

    async def test_expired_final_reply_never_reopens_archived_ticket(self):
        ticket, channel = self.ticket()
        request = interaction(self.guild, self.customer, channel)
        request.followup.send.side_effect = http_error()
        with self.assertRaises(discord.HTTPException):
            await self.service.close_ticket(request, ticket["id"])
        self.assertEqual(self.store.get_ticket(ticket["id"])["status"], "closed")
        self.assertFalse(channel.overwrites[self.customer].view_channel)

    async def test_log_permissions_are_fetched_again_before_transcript_upload(self):
        ticket, channel = self.ticket()
        log_channel = self.create_channel("logs", overwrites={
            self.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            self.guild.me: discord.PermissionOverwrite(view_channel=True),
            self.roles["moderator"]: discord.PermissionOverwrite(view_channel=True)})
        self.store.set_resource("channel", "ticket-logs", log_channel.id)
        public_snapshot = MagicMock(spec=discord.TextChannel)
        public_snapshot.overwrites_for.return_value = discord.PermissionOverwrite(view_channel=True)
        self.guild.fetch_channel = AsyncMock(return_value=public_snapshot)
        await self.service.close_ticket(interaction(self.guild, self.customer, channel), ticket["id"])
        self.guild.fetch_channel.assert_awaited_once_with(log_channel.id)
        log_channel.send.assert_not_called()
        self.assertEqual(self.store.get_ticket(ticket["id"])["status"], "closed")

    async def test_transcript_failure_preserves_channel_and_restores_access(self):
        ticket, channel = self.ticket()
        self.service._transcript = AsyncMock(side_effect=RuntimeError("History incomplete"))
        await self.service.close_ticket(interaction(self.guild, self.customer, channel), ticket["id"])
        self.assertEqual(self.store.get_ticket(ticket["id"])["status"], "open")
        self.assertTrue(channel.overwrites[self.customer].send_messages)
        channel.delete.assert_not_called()

    async def test_failed_permission_recovery_stays_pending_until_sync_repairs_it(self):
        ticket, channel = self.ticket()
        real_edit = channel.edit.side_effect
        channel.edit.side_effect = [http_error(discord.Forbidden, 403), http_error(discord.Forbidden, 403)]
        await self.service.close_ticket(interaction(self.guild, self.customer, channel), ticket["id"])
        self.assertEqual(self.store.get_ticket(ticket["id"])["status"], "closing")
        channel.edit.side_effect = real_edit
        await self.service.restore_views()
        self.assertEqual(self.store.get_ticket(ticket["id"])["status"], "open")
        self.assertTrue(channel.overwrites[self.customer].send_messages)

    async def test_transcript_overflow_does_not_save_partial_archive(self):
        ticket, channel = self.ticket()
        self.config["transcript_limit"] = 1
        await channel.send("First message")
        await channel.send("Second message")
        with self.assertRaisesRegex(RuntimeError, "exceeds transcript_limit"):
            await self.service._transcript(channel, ticket)
        self.assertFalse((self.root / "data" / "transcripts").exists())

    async def test_staff_claim_and_completion_are_idempotent(self):
        ticket, channel = self.ticket()
        await self.service.control(interaction(self.guild, self.staff, channel), ticket["id"], "claim")
        await self.service.control(interaction(self.guild, self.seller, channel), ticket["id"], "claim")
        self.assertEqual(self.store.get_ticket(ticket["id"])["claimed_by"], self.staff.id)
        await self.service.control(interaction(self.guild, self.staff, channel), ticket["id"], "complete")
        await self.service.control(interaction(self.guild, self.seller, channel), ticket["id"], "complete")
        self.assertEqual(len(self.store.recent_orders()), 1)
        self.assertEqual(self.store.recent_orders()[0]["completed_by"], self.staff.id)


if __name__ == "__main__":
    unittest.main()
