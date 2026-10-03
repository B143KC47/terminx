import unittest

from scripts.check_docs import check_text


class DocumentCheckTests(unittest.TestCase):
    def test_checks_long_sentences_and_does_not_count_command_blocks(self):
        long = " ".join(["word"] * 21) + "."
        self.assertTrue(check_text(long, "sample"))
        self.assertFalse(check_text("```powershell\n" + long + "\n```", "sample"))

    def test_keeps_link_text_and_rejects_contractions(self):
        self.assertFalse(
            check_text(
                "Read the [guide](https://example.com/very/long/path).", "sample"
            )
        )
        self.assertTrue(check_text("Don't open the file.", "sample"))

    def test_source_docstrings_cannot_skip_sentence_limits(self):
        self.assertTrue(check_text(" ".join(["word"] * 21), "source docstring"))
