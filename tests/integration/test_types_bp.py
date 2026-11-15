import unittest

from tests.integration.session import SessionTest


class TypesTest(SessionTest):
    def test_layout(self):
        out = self.s.ok("dt sample_s")
        self.assertTrue(out.startswith("sample!sample_s"))
        for expected in ("+0x000 a                : Int4B",
                         "+0x008 name             : Ptr64 Char",
                         "+0x010 in               : inner",
                         "+0x018 arr              : [4] Int4B",
                         "+0x028 flags            : Pos 0, 3 Bits",
                         "+0x028 mode             : Pos 3, 5 Bits",
                         "+0x02c c                : color",
                         "+0x030 d                : Float"):
            self.assertIn(expected, out)

    def test_values(self):
        out = self.s.ok("dt sample_s g_sample")
        for expected in (": 0n5", '"sample"', ": 0y101", ": 0y10001", "0n2 ( BLUE )", ": 1.5", "[4] 0n10"):
            self.assertIn(expected, out)

    def test_recursive_and_arrays(self):
        out = self.s.ok("dt -r -a sample_s g_sample")
        self.assertIn("   +0x004 y                : 0n2", out)
        self.assertIn("[03] 0n40", out)

    def test_field_filter(self):
        out = self.s.lines("dt g_sample in.y")
        self.assertTrue(out[0].startswith("Global var @"))
        self.assertEqual(len(out), 3)
        self.assertIn("+0x004 y", out[2])

    def test_pointer_variable(self):
        self.s.ok(".frame 1")
        try:
            out = self.s.ok("dt s")
            self.assertIn("Local var @", out)
            self.assertIn(": 0n5", out)
        finally:
            self.s.ok(".frame 0")

    def test_wildcard_and_missing(self):
        self.assertIn("sample!sample_s", self.s.ok("dt sample!sam*"))
        self.assertIn("not found", self.s.fail("dt no_such_type"))


class BreakpointTest(SessionTest):
    def test_lifecycle(self):
        self.s.ok("bp middle")
        bl = self.s.lines("bl")
        line = next(l for l in bl if "sample!middle" in l)
        bid = line.split()[0]
        self.assertTrue(any(l.split()[0] == "0" and "sample!leaf" in l for l in bl))
        self.s.ok("bd " + bid)
        self.assertEqual(next(l for l in self.s.lines("bl") if "sample!middle" in l).split()[1], "d")
        self.s.ok("be " + bid)
        self.assertEqual(next(l for l in self.s.lines("bl") if "sample!middle" in l).split()[1], "e")
        self.s.ok("bc " + bid)
        self.assertFalse(any(l.split()[0] == bid for l in self.s.lines("bl")))

    def test_deferred_and_commands(self):
        self.assertIn("deferred", self.s.ok("bu nosuch!function"))
        self.s.ok('bp main+4 "k;g"')
        bl = self.s.ok("bl")
        self.assertIn("(nosuch!function)", bl)
        self.assertIn('"k;g"', bl)

    def test_bm(self):
        self.assertIn('@!"sample!middle', self.s.ok("bm sample!mid*"))

    def test_bad_ids(self):
        self.assertIn("not found", self.s.ok("bd 999"))
        self.s.fail("bc x")


if __name__ == "__main__":
    unittest.main()
