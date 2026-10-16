"""Exercise Discord setup against a stateful in-memory Discord API model."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

import discord
from yarl import URL

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
        self.me.roles = [self.default_role, self.me.top_role]
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

    def bot_permissions_for(self, overwrites):
        """Resolve the fake bot's real channel overrides; no API validation claim."""
        permissions = discord.Permissions(self.me.guild_permissions.value)
        if permissions.administrator:
            return discord.Permissions.all()
        for target in (self.default_role, self.me):
            overwrite = overwrites.get(target)
            if overwrite is not None:
                allow, deny = overwrite.pair()
                permissions.handle_overwrite(allow.value, deny.value)
        return permissions

    async def _create_role(self, **kwargs):
        role = Role(self.next_id(), kwargs.pop("name"), **kwargs)
        self.roles.append(role)
        return role

    async def _create_category(self, name, **kwargs):
        category = Mock(spec=discord.CategoryChannel)
        category.id, category.name = self.next_id(), name
        category.position, category.overwrites = kwargs["position"], kwargs["overwrites"]
        category.permissions_for = Mock(
            side_effect=lambda member: self.bot_permissions_for(category.overwrites))

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
        channel.permissions_for = Mock(
            side_effect=lambda member: self.bot_permissions_for(channel.overwrites))

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

    def effective_bot_permissions(self, overwrites):
        """Resolve channel permissions, rather than using the fake API's shortcut.

        guild_permissions represents the union of the member's guild roles.
        @everyone channel restrictions apply next; the explicit member override
        wins last. The bot has no other role-specific channel overwrite here.
        """
        permissions = discord.Permissions(
            self.guild.default_role.permissions.value
            | self.guild.me.guild_permissions.value
        )
        for target in (self.guild.default_role, self.guild.me):
            overwrite = overwrites.get(target)
            if overwrite is not None:
                allow, deny = overwrite.pair()
                permissions.handle_overwrite(allow.value, deny.value)
        return permissions

    async def test_missing_permission_to_deny_is_reported_before_any_mutation(self):
        labels = {
            "mention_everyone": "Mentionner @everyone",
            "create_public_threads": "Créer des fils publics",
            "create_private_threads": "Créer des fils privés",
            "send_messages_in_threads": "Envoyer des messages dans les fils",
        }
        for permission, label in labels.items():
            with self.subTest(permission=permission):
                self.guild.me.guild_permissions = discord.Permissions(
                    **dict.fromkeys(REQUIRED_BOT_PERMISSIONS, True))
                setattr(self.guild.me.guild_permissions, permission, False)
                with self.assertRaises(ProvisioningError) as caught:
                    await sync_guild(self.bot, self.guild)
                self.assertIn(label, str(caught.exception))
                self.assertIn("interdire aux membres", str(caught.exception))
                self.guild.create_role.assert_not_awaited()
                self.guild.create_category.assert_not_awaited()
                self.guild.create_text_channel.assert_not_awaited()

    async def test_invitation_covers_all_allowed_and_denied_channel_permissions(self):
        from main import invite_permissions

        await sync_guild(self.bot, self.guild)
        policies = [channel.overwrites for channel in
                    self.guild.categories + self.guild.text_channels]
        owner = discord.Object(id=987654321, type=discord.Member)
        for closed, frozen in ((False, False), (False, True), (True, False)):
            policies.append(self.bot.tickets._overwrites(
                self.guild, owner, "rex-lines", closed=closed, frozen=frozen))
        granted = invite_permissions()
        for policy in policies:
            for overwrite in policy.values():
                allow, deny = overwrite.pair()
                # Documented Create Guild Channel rule applies to both masks.
                self.assertEqual((allow.value | deny.value) & ~granted.value, 0)
                self.assertIsNone(overwrite.manage_roles)
                self.assertIsNone(overwrite.administrator)
            for permission in REQUIRED_BOT_PERMISSIONS:
                self.assertTrue(getattr(self.effective_bot_permissions(policy), permission))

    async def test_bot_retains_required_permissions_inside_every_category(self):
        await sync_guild(self.bot, self.guild)
        for category in self.guild.categories:
            with self.subTest(category=category.name):
                effective = self.effective_bot_permissions(category.overwrites)
                for permission in REQUIRED_BOT_PERMISSIONS:
                    self.assertTrue(getattr(effective, permission), permission)
                self.assertFalse(effective.administrator)

    async def test_readonly_parent_retains_reactions_for_public_reviews(self):
        await sync_guild(self.bot, self.guild)
        reviews = self.guild.get_channel(
            self.store.get_resource("channel", "customer-reviews")
        )
        category = self.guild.get_channel(reviews.category_id)
        self.assertFalse(category.overwrites[self.guild.default_role].add_reactions)
        self.assertTrue(reviews.overwrites[self.guild.default_role].add_reactions)

        # A guild-level grant alone does not survive @everyone's parent deny.
        # This was the original local permissions defect. Do not pretend the
        # in-memory API reproduces Discord's server-side grant validation.
        legacy = dict(category.overwrites)
        legacy[self.guild.me] = discord.PermissionOverwrite.from_pair(
            *legacy[self.guild.me].pair()
        )
        legacy[self.guild.me].add_reactions = None
        self.assertTrue(self.guild.me.guild_permissions.add_reactions)
        self.assertFalse(self.effective_bot_permissions(legacy).add_reactions)
        self.assertTrue(
            self.effective_bot_permissions(category.overwrites).add_reactions
        )

        # Resynchronizing a category saved by the earlier version repairs it
        # in place, preserving the already installed channels and panels.
        category.overwrites = legacy
        review_id, panel_id = reviews.id, reviews.messages[0].id
        report = await sync_guild(self.new_bot(), self.guild)
        self.assertEqual(report["categories_created"], 0)
        self.assertEqual(report["channels_created"], 0)
        self.assertEqual(report["panels_created"], 0)
        self.assertEqual(self.store.get_resource("channel", "customer-reviews"), review_id)
        self.assertEqual(reviews.messages[0].id, panel_id)
        self.assertTrue(
            self.effective_bot_permissions(category.overwrites).add_reactions
        )

    async def test_forbidden_names_failed_channel_and_preserves_progress(self):
        reviews = next(
            channel for category in self.settings.structure
            for channel in category.get("channels", [])
            if channel["key"] == "customer-reviews"
        )
        create_channel = self.guild.create_text_channel.side_effect

        async def denied_reviews(name, **kwargs):
            if name == reviews["name"]:
                raise discord.Forbidden(
                    SimpleNamespace(status=403, reason="Forbidden"),
                    {"code": 50013, "message": "Missing Permissions"},
                )
            return await create_channel(name, **kwargs)

        self.guild.create_text_channel.side_effect = denied_reviews
        with self.assertRaises(ProvisioningError) as caught:
            await sync_guild(self.bot, self.guild)
        self.assertIn(reviews["name"], str(caught.exception))
        self.assertIn("HTTP 403", str(caught.exception))
        self.assertIn("code 50013", str(caught.exception))
        self.assertIn("Discord refuse l'étape", str(caught.exception))
        self.assertIsNone(self.store.get_resource("channel", "customer-reviews"))
        stock_channel = self.store.get_resource("channel", "available-stock")
        stock_panel = self.store.get_resource("panel", "available-stock")
        self.assertIsNotNone(stock_channel)
        self.assertIsNotNone(stock_panel)

        self.guild.create_text_channel.side_effect = create_channel
        await sync_guild(self.new_bot(), self.guild)
        self.assertEqual(self.store.get_resource("channel", "available-stock"), stock_channel)
        self.assertEqual(self.store.get_resource("panel", "available-stock"), stock_panel)
        self.assertIsNotNone(self.store.get_resource("panel", "customer-reviews"))

    async def test_restart_repairs_all_four_legacy_parent_denies_without_duplicates(self):
        await sync_guild(self.bot, self.guild)
        category = self.guild.get_channel(self.store.get_resource("category", "shop-information"))
        omitted = ("mention_everyone", "create_public_threads", "create_private_threads",
                   "send_messages_in_threads")
        for permission in omitted:
            setattr(category.overwrites[self.guild.me], permission, None)
            self.assertTrue(getattr(self.guild.me.guild_permissions, permission))
            self.assertFalse(getattr(category.permissions_for(self.guild.me), permission))
        channel_ids = [channel.id for channel in self.guild.text_channels]
        panel_ids = [message.id for channel in self.guild.text_channels for message in channel.messages]

        report = await sync_guild(self.new_bot(), self.guild)

        self.assertEqual(report["categories_created"], 0)
        self.assertEqual(report["channels_created"], 0)
        self.assertEqual(report["panels_created"], 0)
        self.assertEqual([channel.id for channel in self.guild.text_channels], channel_ids)
        self.assertEqual([message.id for channel in self.guild.text_channels
                          for message in channel.messages], panel_ids)
        for permission in omitted:
            self.assertTrue(getattr(category.permissions_for(self.guild.me), permission))

    async def test_forbidden_diagnoses_observed_parent_denies_without_disclosing_response(self):
        from shop import __version__

        create_channel = self.guild.create_text_channel.side_effect
        omitted = ("mention_everyone", "create_public_threads", "create_private_threads",
                   "send_messages_in_threads")
        labels = ("Mentionner @everyone", "Créer des fils publics", "Créer des fils privés",
                  "Envoyer des messages dans les fils")

        async def denied_reviews(name, **kwargs):
            if name.endswith("customer-reviews"):
                # Simulate a snapshot observed at the API failure. This does
                # not assert that Discord necessarily rejects these bits.
                for permission in omitted:
                    setattr(kwargs["category"].overwrites[self.guild.me], permission, None)
                response = SimpleNamespace(
                    status=403, reason="Forbidden", method="POST",
                    url=URL("https://discord.com/api/v10/guilds/123/channels?private=QUERY_SECRET"),
                    request_info=SimpleNamespace(method="POST"),
                    headers={"Authorization": "HEADER_SECRET"},
                )
                raise discord.Forbidden(response, {
                    "code": 50013, "message": "Missing Permissions RESPONSE_SECRET"})
            return await create_channel(name, **kwargs)

        self.guild.create_text_channel.side_effect = denied_reviews
        with self.assertRaises(ProvisioningError) as caught:
            await sync_guild(self.bot, self.guild)
        diagnostic = str(caught.exception)
        self.assertIn(__version__, diagnostic)
        self.assertIn("création", diagnostic)
        self.assertIn("POST /guilds/{id}/channels", diagnostic)
        self.assertIn("Au niveau du serveur", diagnostic)
        self.assertIn("Dans la catégorie", diagnostic)
        server_line = next(line for line in diagnostic.splitlines()
                           if "Au niveau du serveur" in line)
        self.assertIn("aucun", server_line.lower())
        parent_line = next(line for line in diagnostic.splitlines()
                           if "Dans la catégorie" in line)
        for label in labels:
            self.assertIn(label, parent_line)
        for sentinel in ("QUERY_SECRET", "HEADER_SECRET", "RESPONSE_SECRET"):
            self.assertNotIn(sentinel, diagnostic)
        self.assertIsNone(self.store.get_resource("channel", "customer-reviews"))

    async def test_forbidden_modification_distinguishes_existing_channel_permissions(self):
        await sync_guild(self.bot, self.guild)
        reviews = self.guild.get_channel(self.store.get_resource("channel", "customer-reviews"))
        original_channel_id = reviews.id
        original_panel_id = reviews.messages[0].id
        reviews.overwrites[self.guild.me].send_messages = False
        response = SimpleNamespace(
            status=403, reason="Forbidden", method="PATCH",
            url=URL(f"https://discord.com/api/v10/channels/{reviews.id}"),
            request_info=SimpleNamespace(method="PATCH"),
        )
        reviews.edit.side_effect = discord.Forbidden(
            response, {"code": 50013, "message": "Missing Permissions"})

        with self.assertRaises(ProvisioningError) as caught:
            await sync_guild(self.bot, self.guild)

        diagnostic = str(caught.exception)
        self.assertIn("modification", diagnostic)
        self.assertIn("PATCH /channels/{id}", diagnostic)
        for scope in ("Au niveau du serveur", "Dans la catégorie"):
            line = next(line for line in diagnostic.splitlines() if scope in line)
            self.assertIn("aucun", line.lower())
        channel_line = next(line for line in diagnostic.splitlines() if "Dans le salon" in line)
        self.assertIn("Envoyer des messages", channel_line)
        self.assertEqual(self.store.get_resource("channel", "customer-reviews"), original_channel_id)
        self.assertEqual(reviews.messages[0].id, original_panel_id)

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
        server_prices = self.settings.prices["products"][product_id]["Small Tribes"]
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
            for server in ("Small Tribes",)}
        embed = build_product_embed(settings, "element-dust")
        self.assertLessEqual(len(embed), 6000)
        self.assertLessEqual(len(embed.fields), 25)
        self.assertTrue(all(len(field.value) <= 1024 for field in embed.fields))
        price_text = "\n".join(f.value for f in embed.fields)
        for i in range(10):
            self.assertEqual(price_text.count(f"Package {i} "), 1)
        self.assertIn(FIXED_PRICE_RULE, price_text)
        self.assertIn(product["availability"], price_text)
        self.assertTrue(embed.footer.text.endswith(panel_marker("product", "element-dust")))


if __name__ == "__main__":
    unittest.main()
