import unittest

from textutil import slugify


class SlugifyTest(unittest.TestCase):
    def test_simple_title(self):
        self.assertEqual(slugify("Hello World"), "hello-world")

    def test_punctuation_collapses(self):
        self.assertEqual(slugify("Sale -- 50% off!"), "sale-50-off")

    def test_accents_fold(self):
        self.assertEqual(slugify("Crème brûlée"), "creme-brulee")

    def test_max_len_has_no_trailing_hyphen(self):
        self.assertEqual(slugify("alpha beta gamma", max_len=11), "alpha-beta")


if __name__ == "__main__":
    unittest.main()
