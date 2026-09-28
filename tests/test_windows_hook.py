import os
import unittest
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


if __name__ == "__main__":
    unittest.main()

