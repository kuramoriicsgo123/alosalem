"""Exercise Discord setup against a stateful in-memory Discord API model."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

import discord

from shop.presentation import FIXED_PRICE_RULE, build_product_embed, panel_marker
from shop.provisioning import (ProvisioningError, REQUIRED_BOT_PERMISSIONS,
                               ROLE_NAMES, sync_guild)
from shop.settings import load_settings
from shop.storage import Store
from shop.tickets import TicketService


ROOT = Path(__file__).resolve().parents[1]


class Role:
    def __init__(self, identifier, name, position=1, **kwargs):
        self.id, self.name, self.position = identifier, name, position
        self.permissions = kwargs.get("permissions", discord.Permissions.none())
        self.color = kwargs.get("color", discord.Color.default())
        self.managed = False
        self.mentionable = False
        self.edit = AsyncMock(side_effect=self._edit)

    def is_default(self):
        return self.id == 1

    def __ge__(self, other):
        return self.position >= other.position

    async def _edit(self, **kwargs):
        for key, value in kwargs.items():
            if key != "reason":
                setattr(self, key, value)
        return self


class Guild:
    def __init__(self):
        self.id = 123
        self.serial = 1000
        self.default_role = Role(1, "@everyone", 0)
        self.roles = [self.default_role]
        self.categories, self.text_channels = [], []
        self.me = Mock()
        self.me.id = 10
        self.me.top_role = Role(10, "Application role", 100)
        self.me.guild_permissions = discord.Permissions(**dict.fromkeys(REQUIRED_BOT_PERMISSIONS, True))
        self.create_role = AsyncMock(side_effect=self._create_role)
        self.create_category = AsyncMock(side_effect=self._create_category)
        self.create_text_channel = AsyncMock(side_effect=self._create_text_channel)
        self.fetch_roles = AsyncMock(side_effect=lambda: list(self.roles))

    def next_id(self):
        self.serial += 1
        return self.serial

    def get_channel(self, identifier):
        return next((c for c in self.categories + self.text_channels if c.id == identifier), None)

    def get_role(self, identifier):
        return next((r for r in self.roles if r.id == identifier), None)

    async def _create_role(self, **kwargs):
        role = Role(self.next_id(), kwargs.pop("name"), **kwargs)
        self.roles.append(role)
        return role

    async def _create_category(self, name, **kwargs):
        category = Mock(spec=discord.CategoryChannel)
        category.id, category.name = self.next_id(), name
        category.position, category.overwrites = kwargs["position"], kwargs["overwrites"]

        async def edit(**changes):
            for key, value in changes.items():
                if key != "reason":
                    setattr(category, key, value)
            return category

        category.edit = AsyncMock(side_effect=edit)
        self.categories.append(category)
        return category

    async def _create_text_channel(self, name, **kwargs):
        channel = Mock(spec=discord.TextChannel)
        channel.id, channel.name = self.next_id(), name
        channel.category_id = kwargs["category"].id
        channel.position, channel.topic = kwargs["position"], kwargs["topic"]
        channel.overwrites, channel.messages = kwargs["overwrites"], []
        channel.permissions_for = Mock(return_value=self.me.guild_permissions)

        async def edit(**changes):
            for key, value in changes.items():
                if key == "category":
                    channel.category_id = value.id
                elif key != "reason":
                    setattr(channel, key, value)
            return channel

        def set_content(message, embed, view):
            payload = embed.to_dict()
            for image_key in ("image", "thumbnail"):
                if image_key in payload:
                    payload[image_key].update(proxy_url="https://images.discordapp.net/proxy", width=500, height=500)
            message.embeds = [discord.Embed.from_dict(payload)]
            rows = copy.deepcopy(view.to_components()) if view else []
            for index, row in enumerate(rows):
                row["id"] = index + 1
                for child_index, component in enumerate(row["components"]):
                    component["id"] = index * 10 + child_index + 2
            message.components = [SimpleNamespace(to_dict=lambda value=data: copy.deepcopy(value))
                                  for data in rows]

        async def send(*, embed, view, allowed_mentions):
            message = SimpleNamespace(id=self.next_id(), author=self.me)
            set_content(message, embed, view)

            async def edit_message(*, embed, view, allowed_mentions):
                set_content(message, embed, view)
                return message

            message.edit = AsyncMock(side_effect=edit_message)
            channel.messages.append(message)
            return message

        async def fetch_message(identifier):
            message = next((m for m in channel.messages if m.id == identifier), None)
            if message is None:
                response = SimpleNamespace(status=404, reason="Not Found")
                raise discord.NotFound(response, "Unknown Message")
            return message

        async def history(**kwargs):
            for message in list(channel.messages):
                yield message

        channel.edit = AsyncMock(side_effect=edit)
        channel.send = AsyncMock(side_effect=send)
        channel.fetch_message = AsyncMock(side_effect=fetch_message)
        channel.history = history
        self.text_channels.append(channel)
        return channel


class ProvisioningTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "shop.sqlite3"
        self.store = Store(self.path)
        self.guild = Guild()
        self.settings = load_settings(ROOT)
        self.bot = self.new_bot()

    def new_bot(self):
        bot = SimpleNamespace(store=self.store, settings=self.settings, user=self.guild.me)
        bot.tickets = TicketService(bot)
        return bot

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    async def test_second_sync_after_restart_creates_no_duplicates(self):
        self.settings.config["logo_url"] = "https://example.org/shop-logo.png"
        first = await sync_guild(self.bot, self.guild)
        self.assertEqual(first["roles_created"], 7)
        self.assertGreater(first["channels_created"], 60)
        original_ids = {key: self.store.get_resource("channel", key) for key in self.settings.products}
        self.store.close()
        self.store = Store(self.path)
        second = await sync_guild(self.new_bot(), self.guild)
        self.assertEqual(second, dict.fromkeys(first, 0))
        for key, identifier in original_ids.items():
            self.assertEqual(identifier, self.store.get_resource("channel", key))
        self.assertEqual(sum(c.name.endswith("open-a-ticket") for c in self.guild.text_channels), 1)

    async def test_recovers_channels_and_panels_after_resource_database_loss(self):
        first = await sync_guild(self.bot, self.guild)
        with self.store.db:
            self.store.db.execute("DELETE FROM resources")
        second = await sync_guild(self.bot, self.guild)
        self.assertEqual(second, dict.fromkeys(first, 0))
        self.assertTrue(all(len(channel.messages) == 1 for channel in self.guild.text_channels))

    async def test_readonly_private_and_community_permissions_and_real_buttons(self):
        await sync_guild(self.bot, self.guild)
        for product_id, product in self.settings.products.items():
            if not product.get("channel"):
                continue
            channel = self.guild.get_channel(self.store.get_resource("channel", product_id))
            everyone = channel.overwrites[self.guild.default_role]
            self.assertTrue(everyone.view_channel)
            self.assertFalse(everyone.send_messages)
            self.assertFalse(everyone.create_public_threads)
            components = channel.messages[0].components[0].to_dict()["components"]
            self.assertEqual(components[0]["style"], discord.ButtonStyle.success.value)
            self.assertEqual(components[0]["custom_id"], f"shop:buy:{product_id}")
        staff = self.guild.get_channel(self.store.get_resource("channel", "staff-chat"))
        self.assertFalse(staff.overwrites[self.guild.default_role].view_channel)
        for key in self.settings.config["staff_role_keys"]:
            role = self.guild.get_role(self.store.get_resource("role", key))
            self.assertTrue(staff.overwrites[role].view_channel)
            self.assertFalse(role.permissions.administrator)
            self.assertFalse(role.permissions.manage_guild)
        community = self.guild.get_channel(self.store.get_resource("channel", "general-chat"))
        self.assertTrue(community.overwrites[self.guild.default_role].send_messages)
        self.assertTrue(community.overwrites[self.guild.default_role].attach_files)
        central = self.guild.get_channel(self.store.get_resource("channel", "open-a-ticket"))
        self.assertEqual(len(central.messages[0].components), 5)

    async def test_existing_role_privileges_and_existing_topic_are_preserved(self):
        existing_role = Role(99, ROLE_NAMES["moderator"],
                             permissions=discord.Permissions(moderate_members=True))
        self.guild.roles.append(existing_role)
        await sync_guild(self.bot, self.guild)
        self.assertTrue(existing_role.permissions.moderate_members)
        existing_role.edit.assert_not_awaited()
        welcome = self.guild.get_channel(self.store.get_resource("channel", "welcome"))
        welcome.topic = "Useful owner-written topic"
        await sync_guild(self.bot, self.guild)
        self.assertEqual(welcome.topic, "Useful owner-written topic\n" + panel_marker("channel", "welcome"))

    async def test_duplicate_recovery_markers_stop_instead_of_overwriting(self):
        await sync_guild(self.bot, self.guild)
        welcome = self.guild.get_channel(self.store.get_resource("channel", "welcome"))
        duplicate = Mock(spec=discord.TextChannel)
        duplicate.id, duplicate.name, duplicate.topic = 5000, "duplicate", welcome.topic
        self.guild.text_channels.append(duplicate)
        with self.assertRaisesRegex(ProvisioningError, "Several channels"):
            await sync_guild(self.bot, self.guild)

    async def test_adopted_administrator_role_is_rejected_without_mutation(self):
        existing_role = Role(99, ROLE_NAMES["seller"],
                             permissions=discord.Permissions(administrator=True))
        self.guild.roles.append(existing_role)
        with self.assertRaisesRegex(ProvisioningError, "Administrator"):
            await sync_guild(self.bot, self.guild)
        self.assertTrue(existing_role.permissions.administrator)
        existing_role.edit.assert_not_awaited()

    async def test_price_change_updates_saved_panel_in_place(self):
        await sync_guild(self.bot, self.guild)
        product_id = "element-dust"
        old = self.store.get_resource("panel", product_id)
        server_prices = self.settings.prices["products"][product_id]["Official 1x"]
        server_prices[next(iter(server_prices))] = 12.50
        report = await sync_guild(self.bot, self.guild)
        self.assertEqual(report["panels_created"], 0)
        self.assertEqual(report["panels_updated"], 1)
        self.assertEqual(self.store.get_resource("panel", product_id), old)

    async def test_deleted_panel_is_recreated_without_recreating_channel(self):
        await sync_guild(self.bot, self.guild)
        channel_id = self.store.get_resource("channel", "element-dust")
        channel = self.guild.get_channel(channel_id)
        channel.messages.clear()
        report = await sync_guild(self.bot, self.guild)
        self.assertEqual(report["channels_created"], 0)
        self.assertEqual(report["panels_created"], 1)
        self.assertEqual(self.store.get_resource("channel", "element-dust"), channel_id)


class PresentationTests(unittest.TestCase):
    def test_support_request_has_no_sales_or_payment_language(self):
        settings = SimpleNamespace(
            config={"shop_name": "Test shop", "accent_color": "B3202A"},
            products={"support": {"title": "Contact Staff", "description": "Request assistance.",
                                  "commercial": False, "availability": "Staff responds when available."}},
            prices={"products": {}},
        )
        embed = build_product_embed(settings, "support")
        self.assertNotIn("Price", [field.name for field in embed.fields])
        self.assertNotIn("How to order", [field.name for field in embed.fields])
        self.assertIn("No purchase is required", embed.fields[-1].value)

    def test_long_prose_never_eats_prices_availability_or_ordering_rule(self):
        settings = load_settings(ROOT)
        product = settings.products["element-dust"]
        product["description"] = "Description " * 250
        product["fields"] = [{"name": f"Details {i}", "value": "A" * 1024} for i in range(17)]
        product["availability"] = "Available after staff confirmation."
        settings.prices["products"]["element-dust"] = {
            server: {f"Package {i} " + "x" * 50: i + 0.50 for i in range(10)}
            for server in ("Official 1x", "Small Tribes", "PvE")}
        embed = build_product_embed(settings, "element-dust")
        self.assertLessEqual(len(embed), 6000)
        self.assertLessEqual(len(embed.fields), 25)
        self.assertTrue(all(len(field.value) <= 1024 for field in embed.fields))
        price_text = "\n".join(f.value for f in embed.fields)
        for i in range(10):
            self.assertEqual(price_text.count(f"Package {i} "), 3)
        self.assertIn(FIXED_PRICE_RULE, price_text)
        self.assertIn(product["availability"], price_text)
        self.assertTrue(embed.footer.text.endswith(panel_marker("product", "element-dust")))


if __name__ == "__main__":
    unittest.main()
