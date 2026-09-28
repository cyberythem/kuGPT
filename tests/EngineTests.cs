using System;
using KuGPT;

namespace KuGPT.Tests
{
    public static class EngineTests
    {
        private static int failures;

        public static int Main()
        {
            TestCapitalizationAndSpelling();
            TestSentenceReset();
            TestDoubleSpacePunctuation();
            TestEnterPunctuation();
            TestContextCorrection();
            TestBackspace();

            if (failures == 0)
            {
                Console.WriteLine("All engine tests passed.");
                return 0;
            }
            Console.Error.WriteLine(failures + " test(s) failed.");
            return 1;
        }

        private static void TestCapitalizationAndSpelling()
        {
            TextEngine engine = new TextEngine();
            Type(engine, "teh");
            EditPlan plan = engine.CompleteBoundary(BoundaryKind.Space, '\0');
            Equal("The ", plan.InsertText, "capitalizes and corrects first word");
            Equal(3, plan.DeleteCount, "deletes original word");
        }

        private static void TestSentenceReset()
        {
            TextEngine engine = new TextEngine();
            Type(engine, "hello");
            engine.CompleteBoundary(BoundaryKind.Punctuation, '.');
            Type(engine, "next");
            EditPlan plan = engine.CompleteBoundary(BoundaryKind.Space, '\0');
            Equal("Next ", plan.InsertText, "capitalizes after terminal punctuation");
        }

        private static void TestDoubleSpacePunctuation()
        {
            TextEngine engine = new TextEngine();
            Complete(engine, "this"); Complete(engine, "is"); Complete(engine, "ready");
            EditPlan plan = engine.CompleteBoundary(BoundaryKind.Space, '\0');
            Equal(". ", plan.InsertText, "double space inserts punctuation");
            Equal(1, plan.DeleteCount, "double space replaces first space");
        }

        private static void TestEnterPunctuation()
        {
            TextEngine engine = new TextEngine();
            Type(engine, "hello");
            EditPlan plan = engine.CompleteBoundary(BoundaryKind.Enter, '\0');
            Equal("Hello.\r", plan.InsertText, "enter adds period");
        }

        private static void TestContextCorrection()
        {
            TextEngine engine = new TextEngine();
            Complete(engine, "we"); Complete(engine, "should");
            Type(engine, "of");
            EditPlan plan = engine.CompleteBoundary(BoundaryKind.Space, '\0');
            Equal("have ", plan.InsertText, "uses previous word for modal correction");
        }

        private static void TestBackspace()
        {
            TextEngine engine = new TextEngine();
            Type(engine, "tehh");
            engine.Backspace();
            EditPlan plan = engine.CompleteBoundary(BoundaryKind.Space, '\0');
            Equal("The ", plan.InsertText, "backspace updates buffered word");
        }

        private static void Complete(TextEngine engine, string word)
        {
            Type(engine, word);
            engine.CompleteBoundary(BoundaryKind.Space, '\0');
        }

        private static void Type(TextEngine engine, string text)
        {
            foreach (char value in text) engine.TypeCharacter(value);
        }

        private static void Equal(object expected, object actual, string name)
        {
            if (!Object.Equals(expected, actual))
            {
                failures++;
                Console.Error.WriteLine("FAIL " + name + ": expected [" + expected + "] but got [" + actual + "]");
            }
        }
    }
}

