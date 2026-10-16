import asyncio
import contextlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import discord

import main
from shop.locking import InstanceLock
from shop.settings import ConfigurationError, load_settings
from shop.storage import Store
from shop.tickets import MENU_GROUPS, TicketService

ROOT = Path(__file__).resolve().parents[1]


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for name in ("config.example.json", "products.json", "prices.json", "structure.json"):
            shutil.copyfile(ROOT / name, self.root / name)

    def tearDown(self):
        self.temporary.cleanup()

    def edit(self, filename, update):
        path = self.root / filename
        data = json.loads(path.read_text())
        update(data)
        path.write_text(json.dumps(data))

    def test_complete_catalogue_has_one_central_menu_and_no_missing_routes(self):
        settings = load_settings(self.root)
        main.validate_rendering(settings)
        self.assertEqual(len(settings.structure), 11)
        self.assertEqual(sum(c["key"] == "open-a-ticket" for group in settings.structure for c in group["channels"]), 1)
        self.assertTrue(all(pid in settings.products for _, options in MENU_GROUPS for _, pid in options))
        self.assertFalse(any("character-advert" in pid for pid in settings.products))
        self.assertEqual(sum(p["kind"] == "boss" for p in settings.products.values()), 11)
        self.assertEqual(sum(p["kind"] == "dedi" for p in settings.products.values()), 15)

    def test_support_can_omit_prices_but_product_cannot(self):
        settings = load_settings(self.root)
        self.assertIs(settings.products["report-a-scammer"]["commercial"], False)
        self.edit("prices.json", lambda d: d["products"]["rex-lines"].update({"PvE": {}}))
        with self.assertRaises(ConfigurationError):
            load_settings(self.root)

    def test_refuses_secret_in_public_config(self):
        self.edit("config.example.json", lambda d: d.update({"DISCORD_TOKEN": "test-placeholder"}))
        with self.assertRaisesRegex(ConfigurationError, "uniquement dans .env"):
            load_settings(self.root)

    def test_configured_stats_and_screenshots_reach_discord_panel(self):
        settings = load_settings(self.root)
        product = settings.products["rex-lines"]
        product["stats"]["level"] = "Owner supplied value"
        product["screenshots"] = ["https://example.com/rex.png"]
        embed = main.build_product_embed(settings, "rex-lines")
        self.assertEqual(next(field.value for field in embed.fields if field.name == "Level"), "Owner supplied value")
        self.assertEqual(embed.image.url, "https://example.com/rex.png")
        self.assertIn("https://example.com/rex.png", next(field.value for field in embed.fields if field.name == "Screenshots"))

    def test_refuses_data_directory_outside_project(self):
        self.edit("config.example.json", lambda d: d.update({"data_dir": "../external"}))
        with self.assertRaises(ConfigurationError):
            load_settings(self.root)

    def test_refuses_ambiguous_duplicate_channel(self):
        def mutate(data):
            data[1]["channel"] = data[0]["channel"]
        self.edit("products.json", mutate)
        with self.assertRaises(ConfigurationError):
            load_settings(self.root)

    def test_rejects_nan_and_negative_prices(self):
        for invalid in (float("nan"), -1, True, "10 €"):
            self.edit("prices.json", lambda d: d["products"]["rex-lines"]["PvE"].update({"Single Dinosaur": invalid}))
            with self.subTest(invalid=invalid), self.assertRaises(ConfigurationError):
                load_settings(self.root)

    def test_backup_of_live_wal_database_contains_latest_commit(self):
        settings = load_settings(self.root)
        store = Store(settings.data_dir / "shop.sqlite3")
        try:
            store.set_resource("channel", "welcome", 12345)
            backup = main.backup_database(settings)
            with sqlite3.connect(backup) as database:
                self.assertEqual(database.execute("SELECT discord_id FROM resources WHERE key='welcome'").fetchone()[0], 12345)
                self.assertEqual(database.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            store.close()

    def test_cli_check_never_requires_token_or_connects(self):
        with patch.object(main, "ROOT", self.root), patch.object(main, "run_bot") as start:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                result = main.main(["--check"])
            self.assertEqual(result, 0)
            start.assert_not_called()
        from shop import __version__
        self.assertIn(f"Version du bot : {__version__}", output.getvalue())

    def test_cli_missing_configuration_is_actionable(self):
        with patch.object(main, "ROOT", self.root), contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(main.main(["--setup"]), 2)
        self.assertIn("config.example.json", output.getvalue())

    def test_invitation_uses_minimal_permissions(self):
        permissions = main.invite_permissions()
        self.assertFalse(permissions.administrator)
        self.assertFalse(permissions.ban_members)
        self.assertTrue(permissions.manage_channels)
        self.assertTrue(permissions.manage_roles)
        self.assertTrue(permissions.read_message_history)
        self.assertTrue(permissions.add_reactions)
        for name in ("mention_everyone", "create_public_threads", "create_private_threads",
                     "send_messages_in_threads"):
            self.assertTrue(getattr(permissions, name))

    def test_process_lock_prevents_second_instance_and_releases(self):
        path = self.root / "bot.lock"
        first = InstanceLock(path)
        try:
            with self.assertRaisesRegex(RuntimeError, "déjà"):
                InstanceLock(path)
        finally:
            first.close()
        second = InstanceLock(path)
        second.close()


class BotTests(unittest.IsolatedAsyncioTestCase):
    async def test_bot_registers_persistent_catalogue_and_manager_commands_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "shop.sqlite3")
            settings = load_settings(ROOT)
            bot = main.ShopBot(settings, store, False)
            try:
                await bot.tickets.restore_views()
                self.assertEqual(len(bot.persistent_views), len(settings.products) + 1)
                commands = {command.name for command in bot.tree.get_commands()}
                self.assertEqual(commands, {"shop_sync", "shop_status", "shop_orders", "shop_announce"})
                self.assertTrue(bot.intents.members)
                self.assertTrue(bot.intents.message_content)
            finally:
                await bot.close()
                store.close()


if __name__ == "__main__":
    unittest.main()
