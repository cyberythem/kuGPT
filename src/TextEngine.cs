using System;
using System.Collections.Generic;
using System.Text;

namespace KuGPT
{
    public enum BoundaryKind
    {
        Space,
        Enter,
        Punctuation
    }

    public sealed class EditPlan
    {
        public int DeleteCount { get; private set; }
        public string InsertText { get; private set; }
        public string OriginalText { get; private set; }

        public EditPlan(int deleteCount, string insertText, string originalText)
        {
            DeleteCount = deleteCount;
            InsertText = insertText;
            OriginalText = originalText;
        }
    }

    public sealed class TextEngine
    {
        private static readonly Dictionary<string, string> Corrections =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                { "adn", "and" }, { "agian", "again" }, { "alot", "a lot" },
                { "becuase", "because" }, { "beleive", "believe" },
                { "cant", "can't" }, { "couldnt", "couldn't" },
                { "definately", "definitely" }, { "didnt", "didn't" },
                { "doesnt", "doesn't" }, { "dont", "don't" },
                { "everytime", "every time" }, { "happend", "happened" },
                { "hasnt", "hasn't" }, { "havent", "haven't" },
                { "hte", "the" }, { "im", "I'm" }, { "ive", "I've" },
                { "isnt", "isn't" }, { "jsut", "just" }, { "knwo", "know" },
                { "langauge", "language" }, { "occured", "occurred" },
                { "recieve", "receive" }, { "seperate", "separate" },
                { "shoudl", "should" }, { "teh", "the" },
                { "thier", "their" }, { "tommorow", "tomorrow" },
                { "untill", "until" }, { "wasnt", "wasn't" },
                { "werent", "weren't" }, { "wont", "won't" },
                { "wouldnt", "wouldn't" }, { "youre", "you're" }
            };

        private readonly StringBuilder currentWord = new StringBuilder();
        private string previousWord = String.Empty;
        private bool sentenceStart = true;
        private bool sentenceHasTerminalPunctuation;
        private int wordsInSentence;
        private bool lastInputWasSpace;

        public string CurrentWord { get { return currentWord.ToString(); } }

        public void TypeCharacter(char value)
        {
            if (Char.IsLetter(value) || value == '\'' || value == '-')
            {
                currentWord.Append(value);
                lastInputWasSpace = false;
                sentenceHasTerminalPunctuation = false;
            }
            else
            {
                ResetWord();
            }
        }

        public void Backspace()
        {
            if (currentWord.Length > 0)
            {
                currentWord.Length--;
            }
            else
            {
                ResetContext();
            }
            lastInputWasSpace = false;
        }

        public EditPlan CompleteBoundary(BoundaryKind kind, char punctuation)
        {
            string word = currentWord.ToString();
            string boundary = BoundaryText(kind, punctuation);

            if (word.Length > 0)
            {
                string corrected = CorrectWord(word);
                bool startsSentence = sentenceStart;
                if (startsSentence)
                {
                    corrected = Capitalize(corrected);
                }

                wordsInSentence++;
                previousWord = LastToken(corrected);
                currentWord.Length = 0;
                sentenceStart = false;
                lastInputWasSpace = kind == BoundaryKind.Space;

                if (kind == BoundaryKind.Punctuation && IsTerminal(punctuation))
                {
                    EndSentence();
                }
                else if (kind == BoundaryKind.Enter)
                {
                    if (!sentenceHasTerminalPunctuation)
                    {
                        corrected += ".";
                    }
                    EndSentence();
                }

                string replacement = corrected + boundary;
                string original = word + boundary;
                if (!String.Equals(replacement, original, StringComparison.Ordinal))
                {
                    return new EditPlan(word.Length, replacement, original);
                }
                return null;
            }

            if (kind == BoundaryKind.Space && lastInputWasSpace &&
                wordsInSentence >= 3 && !sentenceHasTerminalPunctuation)
            {
                EndSentence();
                return new EditPlan(1, ". ", "  ");
            }

            if (kind == BoundaryKind.Enter)
            {
                if (wordsInSentence > 0 && !sentenceHasTerminalPunctuation)
                {
                    EndSentence();
                    return new EditPlan(0, ".\r", "\r");
                }
                EndSentence();
            }
            else if (kind == BoundaryKind.Punctuation && IsTerminal(punctuation))
            {
                EndSentence();
            }

            lastInputWasSpace = kind == BoundaryKind.Space;
            return null;
        }

        public void ResetContext()
        {
            currentWord.Length = 0;
            previousWord = String.Empty;
            sentenceStart = true;
            sentenceHasTerminalPunctuation = false;
            wordsInSentence = 0;
            lastInputWasSpace = false;
        }

        private string CorrectWord(string word)
        {
            string replacement;
            if (String.Equals(word, "of", StringComparison.OrdinalIgnoreCase) &&
                IsModal(previousWord))
            {
                replacement = "have";
            }
            else if (!Corrections.TryGetValue(word, out replacement))
            {
                return word;
            }
            return MatchCase(word, replacement);
        }

        private static bool IsModal(string word)
        {
            return String.Equals(word, "could", StringComparison.OrdinalIgnoreCase) ||
                   String.Equals(word, "would", StringComparison.OrdinalIgnoreCase) ||
                   String.Equals(word, "should", StringComparison.OrdinalIgnoreCase) ||
                   String.Equals(word, "might", StringComparison.OrdinalIgnoreCase) ||
                   String.Equals(word, "must", StringComparison.OrdinalIgnoreCase);
        }

        private static string MatchCase(string original, string replacement)
        {
            if (original.Length > 1 && original == original.ToUpperInvariant())
            {
                return replacement.ToUpperInvariant();
            }
            if (Char.IsUpper(original[0]))
            {
                return Capitalize(replacement);
            }
            return replacement;
        }

        private static string Capitalize(string value)
        {
            if (String.IsNullOrEmpty(value) || Char.IsUpper(value[0]))
            {
                return value;
            }
            return Char.ToUpperInvariant(value[0]) + value.Substring(1);
        }

        private static string LastToken(string value)
        {
            int index = value.LastIndexOf(' ');
            return index < 0 ? value : value.Substring(index + 1);
        }

        private static string BoundaryText(BoundaryKind kind, char punctuation)
        {
            if (kind == BoundaryKind.Space) return " ";
            if (kind == BoundaryKind.Enter) return "\r";
            return punctuation.ToString();
        }

        private static bool IsTerminal(char value)
        {
            return value == '.' || value == '!' || value == '?';
        }

        private void EndSentence()
        {
            sentenceStart = true;
            sentenceHasTerminalPunctuation = true;
            wordsInSentence = 0;
            previousWord = String.Empty;
            lastInputWasSpace = false;
        }

        private void ResetWord()
        {
            currentWord.Length = 0;
            lastInputWasSpace = false;
        }
    }
}

