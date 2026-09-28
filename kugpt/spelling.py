from __future__ import annotations

from collections import defaultdict
from pathlib import Path


class SymSpell:
    """Small dependency-free SymSpell-style spelling provider.

    Every dictionary word is used to recognize valid spelling. Delete indexes are
    generated only for the most frequent words, keeping startup and memory modest.
    """

    def __init__(self, dictionary_path: Path, indexed_words: int = 25_000):
        self.dictionary_path = Path(dictionary_path)
        self.indexed_words = indexed_words
        self.words: set[str] = set()
        self.entries: list[tuple[str, int]] = []
        self.deletes: dict[str, list[int]] = defaultdict(list)
        self.cache: dict[str, str | None] = {}
        self._load()

    @property
    def available(self) -> bool:
        return bool(self.words)

    def _load(self) -> None:
        if not self.dictionary_path.is_file():
            raise FileNotFoundError(f"SymSpell dictionary is missing: {self.dictionary_path}")

        with self.dictionary_path.open("r", encoding="utf-8-sig") as stream:
            for line in stream:
                try:
                    word, raw_frequency = line.rsplit(maxsplit=1)
                    frequency = int(raw_frequency)
                except ValueError:
                    continue
                word = word.casefold()
                if not word or word in self.words:
                    continue
                self.words.add(word)
                if len(self.entries) < self.indexed_words:
                    self.entries.append((word, frequency))

        for index, (word, _) in enumerate(self.entries):
            for deletion in generate_deletes(word):
                self.deletes[deletion].append(index)

    def suggest(self, word: str) -> str | None:
        normalized = word.casefold()
        if not normalized or normalized in self.words:
            return None
        if normalized in self.cache:
            return self.cache[normalized]

        best: str | None = None
        best_distance = 3
        best_score = -1.0
        inspected: set[int] = set()
        for deletion in generate_deletes(normalized):
            for index in self.deletes.get(deletion, ()):
                if index in inspected:
                    continue
                inspected.add(index)
                candidate, frequency = self.entries[index]
                distance = damerau_levenshtein(normalized, candidate, 2)
                if distance > 2:
                    continue
                length_delta = abs(len(normalized) - len(candidate))
                score = frequency / (10**length_delta)
                if distance < best_distance or (distance == best_distance and score > best_score):
                    best = candidate
                    best_distance = distance
                    best_score = score

        self.cache[normalized] = best
        return best


def generate_deletes(word: str, max_distance: int = 2, prefix_length: int = 7) -> set[str]:
    prefix = word[:prefix_length]
    results = {prefix}
    level = {prefix}
    for _ in range(max_distance):
        next_level: set[str] = set()
        for candidate in level:
            for index in range(len(candidate)):
                deletion = candidate[:index] + candidate[index + 1 :]
                if deletion not in results:
                    results.add(deletion)
                    next_level.add(deletion)
        level = next_level
    return results


def damerau_levenshtein(source: str, target: str, maximum: int = 2) -> int:
    if abs(len(source) - len(target)) > maximum:
        return maximum + 1
    previous_previous: list[int] | None = None
    previous = list(range(len(target) + 1))
    for i, source_char in enumerate(source, 1):
        current = [i]
        row_minimum = i
        for j, target_char in enumerate(target, 1):
            value = min(
                current[j - 1] + 1,
                previous[j] + 1,
                previous[j - 1] + (source_char != target_char),
            )
            if (
                previous_previous is not None
                and i > 1
                and j > 1
                and source_char == target[j - 2]
                and source[i - 2] == target_char
            ):
                value = min(value, previous_previous[j - 2] + (source_char != target_char))
            current.append(value)
            row_minimum = min(row_minimum, value)
        if row_minimum > maximum:
            return maximum + 1
        previous_previous, previous = previous, current
    return previous[-1]

