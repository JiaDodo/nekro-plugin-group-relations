import unittest
from types import SimpleNamespace

import bootstrap
from group_relations.service import extract, sender_identity


class ExtractTests(unittest.TestCase):
    def message(self, ext):
        return SimpleNamespace(content_data=[{"type": "at", "target_platform_userid": "bot"},
                                             {"type": "at", "target_platform_userid": "b"}],
            ext_data=ext, platform_userid="a", sender_id="a", message_id="1",
            sender_nickname="甲", sender_name="甲", send_timestamp=100, chat_key="g", content_text="")

    def test_bot_mentions_and_replies_preserved(self):
        row = extract(self.message({"ref_msg_id":"bot-message", "ref_sender_id":"bot"}), "bot")
        self.assertEqual(row["mentions"], ["b", "bot"])
        self.assertEqual(row["reply_sender"], "bot")

    def test_bot_identity_and_system_notification_separated(self):
        self.assertEqual(sender_identity("-1", "12345", "12345", "机器人"), "12345")
        self.assertEqual(sender_identity("-1", "", "12345", "机器人"), "12345")
        self.assertEqual(sender_identity("-1", "0", "12345", "SYSTEM"), "")
        self.assertEqual(sender_identity("-1", "", "12345", "SYSTEM"), "")
        self.assertEqual(sender_identity("-1", ""), "")

    def test_cross_group_reply_removed(self):
        row = extract(self.message({"ref_chat_key": "other", "ref_msg_id": "r", "ref_sender_id": "b"}))
        self.assertEqual(row["reply"], "")
        self.assertEqual(row["reply_sender"], "")

    def test_raw_content_not_retained(self):
        message = self.message({})
        message.content_text = "a private message body"
        row = extract(message)
        self.assertNotIn("content_text", row)
        self.assertNotIn(message.content_text, str(row))
