import unittest

from tests.integration.session import SessionTest, parse_addr


class MemoryTest(SessionTest):
    def test_db(self):
        out = self.s.lines("db g_bytes L20")
        self.assertEqual(len(out), 2)
        self.assertIn("00 01 02 03 04 05 06 07-08 09 0a 0b 0c 0d 0e 0f  ................", out[0])

    def test_db_continuation(self):
        first = self.s.lines("db g_bytes L10")
        nxt = self.s.lines("db")
        self.assertEqual(parse_addr(nxt[0]), parse_addr(first[0]) + 0x10)
        self.assertIn("10 11 12 13", nxt[0])

    def test_dd_dq_dw(self):
        self.assertIn("feedface", self.s.ok("dd g_magic L1"))
        self.assertIn("00000000`00000005", self.s.ok("dq g_sample L1"))
        self.assertIn("0100 0302", self.s.ok("dw g_bytes L2"))

    def test_dc(self):
        out = self.s.ok("dc g_ascii L4")
        self.assertIn("6c6c6548", out)
        self.assertIn("Hello, WinLLDB!", out)

    def test_strings(self):
        self.assertIn('"Hello, WinLLDB!"', self.s.ok("da g_ascii"))
        self.assertIn('"Hello"', self.s.ok("da g_ascii L5"))
        self.assertIn('"Wide string"', self.s.ok("du g_wide"))

    def test_dps_symbolizes(self):
        self.assertIn("sample!middle+0x", self.s.ok("dps @rsp L4"))

    def test_bad_address(self):
        self.assertIn("????", self.s.ok("db 0 L10"))


class DisasmTest(SessionTest):
    def test_u(self):
        out = self.s.lines("u leaf L3")
        self.assertEqual(out[0], "sample!leaf:")
        self.assertEqual(len(out), 4)

    def test_u_continuation(self):
        first = self.s.lines("u leaf L2")
        nxt = self.s.lines("u L1")
        self.assertGreater(parse_addr(nxt[-1]), parse_addr(first[-1]))

    def test_ub_ends_at_target(self):
        pc = parse_addr(self.s.lines("u @rip L1")[1])
        insts = [l for l in self.s.lines("ub @rip L4") if parse_addr(l) is not None]
        self.assertEqual(len(insts), 4)
        last = parse_addr(insts[-1])
        self.assertLess(last, pc)
        after = [l for l in self.s.lines("u %x L2" % last) if parse_addr(l) is not None]
        self.assertEqual(parse_addr(after[1]), pc)

    def test_uf(self):
        out = self.s.lines("uf leaf")
        self.assertEqual(out[0], "sample!leaf:")
        self.assertIn("ret", out[-1])

    def test_uf_calls(self):
        self.assertIn("call to sample!leaf", self.s.ok("uf /c middle"))

    def test_riprel_symbolized(self):
        self.assertIn("[sample!g_counter (", self.s.ok("uf leaf"))


if __name__ == "__main__":
    unittest.main()
