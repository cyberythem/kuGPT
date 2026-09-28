from __future__ import annotations

from dataclasses import dataclass

from .spelling import SymSpell, damerau_levenshtein


@dataclass(frozen=True)
class EditPlan:
    delete_count: int
    insert_text: str
    original_text: str


BUILT_INS = {
    "alot": "a lot", "cant": "can't", "couldnt": "couldn't",
    "definately": "definitely", "didnt": "didn't", "doesnt": "doesn't",
    "dont": "don't", "everytime": "every time", "hasnt": "hasn't",
    "havent": "haven't", "im": "I'm", "ive": "I've", "isnt": "isn't",
    "recieve": "receive", "seperate": "separate", "teh": "the",
    "thier": "their", "wont": "won't", "wouldnt": "wouldn't",
    "youre": "you're",
}
MODALS = {"could", "would", "should", "might", "must"}


class TextEngine:
    def __init__(self, spelling: SymSpell):
        self.spelling = spelling
        self.reset_context()

    def reset_context(self) -> None:
        self.current_word = ""
        self.previous_word = ""
        self.sentence_start = True
        self.sentence_has_terminal = False
        self.words_in_sentence = 0
        self.last_input_was_space = False

    def type_character(self, value: str) -> None:
        if value.isalpha() or value in "'-":
            self.current_word += value
            self.last_input_was_space = False
            self.sentence_has_terminal = False
        else:
            self.current_word = ""
            self.last_input_was_space = False

    def backspace(self) -> None:
        if self.current_word:
            self.current_word = self.current_word[:-1]
        else:
            self.reset_context()
        self.last_input_was_space = False

    def complete_boundary(self, kind: str, punctuation: str = "") -> EditPlan | None:
        word = self.current_word
        boundary = {"space": " ", "enter": "\r"}.get(kind, punctuation)
        if word:
            corrected = self._correct_word(word)
            if self.sentence_start:
                corrected = capitalize(corrected)
            self.words_in_sentence += 1
            self.previous_word = corrected.rsplit(" ", 1)[-1]
            self.current_word = ""
            self.sentence_start = False
            self.last_input_was_space = kind == "space"
            if kind == "punctuation" and punctuation in ".!?":
                self._end_sentence()
            elif kind == "enter":
                if not self.sentence_has_terminal:
                    corrected += "."
                self._end_sentence()
            replacement = corrected + boundary
            original = word + boundary
            if replacement != original:
                return EditPlan(len(word), replacement, original)
            return None

        if kind == "space" and self.last_input_was_space and self.words_in_sentence >= 3 and not self.sentence_has_terminal:
            self._end_sentence()
            return EditPlan(1, ". ", "  ")
        if kind == "enter":
            if self.words_in_sentence and not self.sentence_has_terminal:
                self._end_sentence()
                return EditPlan(0, ".\r", "\r")
            self._end_sentence()
        elif kind == "punctuation" and punctuation in ".!?":
            self._end_sentence()
        self.last_input_was_space = kind == "space"
        return None

    def _correct_word(self, word: str) -> str:
        lowered = word.casefold()
        if lowered == "of" and self.previous_word.casefold() in MODALS:
            replacement = "have"
        else:
            replacement = BUILT_INS.get(lowered) or self.spelling.suggest(word)
            if not confident(word, replacement):
                return word
        return match_case(word, replacement)

    def _end_sentence(self) -> None:
        self.sentence_start = True
        self.sentence_has_terminal = True
        self.words_in_sentence = 0
        self.previous_word = ""
        self.last_input_was_space = False


def confident(original: str, suggestion: str | None) -> bool:
    if not suggestion or " " in suggestion or "-" in suggestion or len(original) < 3:
        return False
    distance = damerau_levenshtein(original.casefold(), suggestion.casefold(), 2)
    return distance == 1 or (distance == 2 and len(original) >= 7)


def match_case(original: str, replacement: str) -> str:
    if len(original) > 1 and original.isupper():
        return replacement.upper()
    if original[0].isupper():
        return capitalize(replacement)
    return replacement


def capitalize(value: str) -> str:
    return value if not value or value[0].isupper() else value[0].upper() + value[1:]


def correct_text(engine: TextEngine, text: str) -> str:
    """Deterministically exercise the same word-boundary path used by the hook."""
    output = ""
    for char in text:
        if char.isalpha() or char in "'-":
            engine.type_character(char)
            output += char
            continue
        if char == " ":
            plan = engine.complete_boundary("space")
        elif char in ".!?,;:":
            plan = engine.complete_boundary("punctuation", char)
        elif char in "\r\n":
            plan = engine.complete_boundary("enter")
        else:
            engine.reset_context()
            plan = None
        if plan:
            output = output[:-plan.delete_count] + plan.insert_text
        else:
            output += char
    return output

