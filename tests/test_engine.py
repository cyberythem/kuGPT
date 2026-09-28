import unittest
from pathlib import Path

from kugpt.engine import TextEngine, correct_text
from kugpt.spelling import SymSpell, damerau_levenshtein


ROOT = Path(__file__).resolve().parents[1]


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spelling = SymSpell(ROOT / "data" / "frequency_dictionary_en_82_765.txt")

    def test_reported_sentence(self):
        actual = correct_text(TextEngine(self.spelling), "i am nto tehe ncie pesron ")
        self.assertEqual("I am not the nice person ", actual)

    def test_first_word_and_common_typo(self):
        actual = correct_text(TextEngine(self.spelling), "teh cat ")
        self.assertEqual("The cat ", actual)

    def test_context_rule(self):
        actual = correct_text(TextEngine(self.spelling), "we should of ")
        self.assertEqual("We should have ", actual)

    def test_double_space_punctuation(self):
        actual = correct_text(TextEngine(self.spelling), "this is ready  ")
        self.assertEqual("This is ready. ", actual)

    def test_enter_punctuation(self):
        actual = correct_text(TextEngine(self.spelling), "hello\n")
        self.assertEqual("Hello.\r", actual)

    def test_valid_dictionary_word_is_unchanged(self):
        self.assertIsNone(self.spelling.suggest("keyboard"))

    def test_transposition_distance(self):
        self.assertEqual(1, damerau_levenshtein("nto", "not"))

    def test_unknown_context_does_not_capitalize(self):
        engine = TextEngine(self.spelling)
        engine.reset_context()
        self.assertEqual("the cat ", correct_text(engine, "teh cat "))

    def test_custom_name_is_kept(self):
        self.assertEqual("kugpt kuGPT ", correct_text(TextEngine(self.spelling), "kugpt kuGPT "))

    def test_rejected_correction_is_not_repeated(self):
        engine = TextEngine(self.spelling, initial_sentence_start=False)
        self.assertEqual("the ", correct_text(engine, "teh "))
        self.assertEqual("teh", engine.accept_word("teh"))
        engine.reset_context()
        self.assertEqual("teh ", correct_text(engine, "teh "))

    def test_middle_sentence_title_case_is_kept(self):
        engine = TextEngine(self.spelling, initial_sentence_start=False)
        self.assertEqual("my kuGPT Test ", correct_text(engine, "my kuGPT Test "))


if __name__ == "__main__":
    unittest.main()

