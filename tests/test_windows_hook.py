import os
import ctypes
import unittest
from pathlib import Path
from unittest.mock import call, patch


@unittest.skipUnless(os.name == "nt", "Windows keyboard hook")
class WindowsHookTests(unittest.TestCase):
    def test_replacement_messages_are_sent_in_order(self):
        from kugpt import windows_hook as hook

        with patch.object(hook, "focused_window", return_value=123), patch.object(hook, "send_message") as sent:
            hook.send_replacement(2, "The ")

        self.assertEqual(
            [
                call(123, hook.WM_KEYDOWN, hook.VK_BACK),
                call(123, hook.WM_KEYUP, hook.VK_BACK),
                call(123, hook.WM_KEYDOWN, hook.VK_BACK),
                call(123, hook.WM_KEYUP, hook.VK_BACK),
                call(123, hook.WM_CHAR, ord("T")),
                call(123, hook.WM_CHAR, ord("h")),
                call(123, hook.WM_CHAR, ord("e")),
                call(123, hook.WM_CHAR, ord(" ")),
            ],
            sent.call_args_list,
        )

    def test_rewritten_word_is_accepted_after_backspacing(self):
        from kugpt import windows_hook as hook
        from kugpt.engine import TextEngine
        from kugpt.spelling import SymSpell

        dictionary = Path(__file__).resolve().parents[1] / "data" / "frequency_dictionary_en_82_765.txt"
        engine = TextEngine(SymSpell(dictionary), initial_sentence_start=False)
        daemon = hook.KeyboardDaemon(engine, Path("nonexistent-pause-file"))
        edits = []

        def key(vk, character=None):
            data = hook.KBDLLHOOKSTRUCT(vkCode=vk)
            with patch.object(hook, "translate_key", return_value=character):
                daemon._callback(0, hook.WM_KEYDOWN, ctypes.addressof(data))
                daemon._callback(0, hook.WM_KEYUP, ctypes.addressof(data))

        with (
            patch.object(hook.user32, "GetForegroundWindow", return_value=123),
            patch.object(hook, "sensitive_target", return_value=False),
            patch.object(hook, "is_known_document_start", return_value=False),
            patch.object(hook, "send_replacement", side_effect=lambda count, text: edits.append((count, text))),
        ):
            for char in "teh":
                key(ord(char.upper()), char)
            key(hook.VK_SPACE, " ")
            self.assertEqual((3, "the "), edits[-1])

            key(hook.VK_BACK)
            key(hook.VK_BACK)
            self.assertIn("teh", engine.accepted_words)

            for char in "teh":
                key(ord(char.upper()), char)
            key(hook.VK_SPACE, " ")
            self.assertEqual((0, " "), edits[-1])


if __name__ == "__main__":
    unittest.main()

