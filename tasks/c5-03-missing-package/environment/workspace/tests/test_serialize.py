import unittest

from app.serialize import dumps


class SerializeTest(unittest.TestCase):
    def test_sorted_and_compact(self):
        self.assertEqual(dumps({"b": 1, "a": [1, 2]}), '{"a":[1,2],"b":1}')


if __name__ == "__main__":
    unittest.main()
