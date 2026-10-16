"""Preserve legacy PvE channel history while retiring its public sales panel."""
from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import discord

from shop.presentation import panel_marker
from shop.provisioning import ProvisioningError, ROLE_NAMES, _retire_pve_bases, sync_guild
from shop.settings import load_settings
from shop.storage import Store
from shop.tickets import TicketService
from test_provisioning import Guild


ROOT = Path(__file__).resolve().parents[1]


class SmallTribesRetirementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "shop.sqlite3")
        self.guild = Guild()
        settings = load_settings(ROOT)
        settings.products.pop("pve-bases", None)
        self.bot = SimpleNamespace(store=self.store, settings=settings, user=self.guild.me)
        self.bot.tickets = TicketService(self.bot)
        await sync_guild(self.bot, self.guild)
        self.roles = {key: self.guild.get_role(self.store.get_resource("role", key)) for key in ROLE_NAMES}
        self.summary = {"panels_created": 0, "panels_updated": 0}

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    async def legacy_channel(self):
        category = self.guild.get_channel(self.store.get_resource("category", "base-sales"))
        channel = await self.guild.create_text_channel(
            "🏘️・pve-bases", category=category, position=99,
            topic=panel_marker("channel", "pve-bases"), overwrites=dict(category.overwrites),
        )
        channel.guild = self.guild
        self.store.set_resource("channel", "pve-bases", channel.id)
        embed = discord.Embed(title="PVE BASES", description="Legacy listing")
        embed.set_footer(text="Shop • " + panel_marker("product", "pve-bases"))
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Buy Base", style=discord.ButtonStyle.success,
                                       custom_id="legacy-buy-base"))
        panel = await channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        self.store.set_resource("panel", "pve-bases", panel.id)
        history_message = await channel.send(embed=discord.Embed(description="Existing staff note"),
                                             view=None, allowed_mentions=discord.AllowedMentions.none())
        return channel, panel, history_message

    async def test_sync_retires_known_channel_privately_and_preserves_history_idempotently(self):
        channel, panel, history_message = await self.legacy_channel()
        original_channel_id, original_panel_id = channel.id, panel.id
        original_count = len(self.guild.text_channels)
        summary = await sync_guild(self.bot, self.guild)
        self.assertEqual(channel.category_id, self.store.get_resource("category", "staff-only"))
        self.assertEqual(channel.name, "retired-pve-bases")
        self.assertFalse(channel.overwrites[self.guild.default_role].view_channel)
        self.assertFalse(channel.overwrites[self.guild.default_role].read_message_history)
        for key in self.bot.settings.config["staff_role_keys"]:
            self.assertTrue(channel.overwrites[self.roles[key]].view_channel)
        self.assertEqual(panel.components, [])
        self.assertIn("Small Tribes only", panel.embeds[0].description)
        self.assertEqual(channel.messages, [panel, history_message])
        history_message.edit.assert_not_awaited()
        self.assertEqual(summary["panels_updated"], 1)
        channel.edit.assert_awaited_once()
        panel.edit.assert_awaited_once()
        second = await sync_guild(self.bot, self.guild)
        self.assertEqual(second["panels_updated"], 0)
        self.assertEqual(len(self.guild.text_channels), original_count)
        self.assertEqual(self.store.get_resource("channel", "pve-bases"), original_channel_id)
        self.assertEqual(self.store.get_resource("panel", "pve-bases"), original_panel_id)
        channel.edit.assert_awaited_once()
        panel.edit.assert_awaited_once()

    async def test_refuses_unmarked_mismatched_and_foreign_channels_without_mutation(self):
        channel, panel, _ = await self.legacy_channel()
        for topic, guild in [
            ("Unrelated public channel", self.guild),
            (panel_marker("channel", "other-key"), self.guild),
            (panel_marker("channel", "pve-bases") + "\n" + panel_marker("channel", "other-key"), self.guild),
            (panel_marker("channel", "pve-bases"), SimpleNamespace(id=999)),
        ]:
            with self.subTest(topic=topic, guild_id=guild.id):
                channel.topic, channel.guild = topic, guild
                with self.assertRaisesRegex(ProvisioningError, "laissé intact"):
                    await _retire_pve_bases(self.bot, self.guild, self.roles, self.summary)
                channel.edit.assert_not_awaited()
                panel.edit.assert_not_awaited()
                self.assertTrue(panel.components)

    async def test_missing_staff_category_leaves_legacy_channel_untouched(self):
        channel, panel, _ = await self.legacy_channel()
        self.store.delete_resource("category", "staff-only")
        with self.assertRaisesRegex(ProvisioningError, "catégorie privée"):
            await _retire_pve_bases(self.bot, self.guild, self.roles, self.summary)
        channel.edit.assert_not_awaited()
        panel.edit.assert_not_awaited()

    async def test_missing_saved_channel_does_not_adopt_unmanaged_channel_by_name(self):
        channel, panel, _ = await self.legacy_channel()
        self.store.delete_resource("channel", "pve-bases")
        await _retire_pve_bases(self.bot, self.guild, self.roles, self.summary)
        channel.edit.assert_not_awaited()
        panel.edit.assert_not_awaited()

    async def test_saved_unrelated_panel_is_never_overwritten(self):
        channel, panel, history_message = await self.legacy_channel()
        self.store.set_resource("panel", "pve-bases", history_message.id)
        with self.assertRaisesRegex(ProvisioningError, "left untouched"):
            await _retire_pve_bases(self.bot, self.guild, self.roles, self.summary)
        panel.edit.assert_not_awaited()
        history_message.edit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
