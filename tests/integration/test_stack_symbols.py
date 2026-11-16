import unittest

from tests.integration.session import Session, SessionTest


class StackRegistersTest(SessionTest):
    def test_k(self):
        out = self.s.lines("k")
        self.assertTrue(out[0].startswith(" # Child-SP"))
        self.assertEqual([l.split()[0] for l in out[1:4]], ["00", "01", "02"])
        sites = [l.split()[3] for l in out[1:4]]
        self.assertEqual([s.split("+")[0] for s in sites], ["sample!leaf", "sample!middle", "sample!main"])

    def test_kn_kp_kb(self):
        self.assertTrue(self.s.lines("kn")[1].startswith("00 "))
        kp = self.s.lines("kp")
        self.assertTrue(kp[0].startswith(" # Child-SP"))
        self.assertTrue(kp[1].startswith("00 "))
        self.assertIn("sample!leaf(int v = 0n8)", kp[1])
        self.assertTrue(any("sample!main(void)" in l for l in kp))
        self.assertIn("Args to Child", self.s.ok("kb 1"))
        self.assertEqual(len(self.s.lines("kc 2")), 3)

    def test_r(self):
        out = self.s.ok("r")
        for expected in ("rax=", "rip=", " r8=", "iopl=", "efl=", "sample!leaf+0x"):
            self.assertIn(expected, out)

    def test_r_set(self):
        self.s.ok("r rbx=1234")
        self.assertEqual(self.s.ok("r rbx").strip(), "rbx=0000000000001234")
        self.assertIn("Evaluate expression: 4660", self.s.ok("? @rbx"))

    def test_frame_and_threads(self):
        self.assertIn("sample!middle", self.s.ok(".frame 1"))
        self.s.ok(".frame 0")
        self.assertTrue(self.s.lines("~")[0].startswith(".  0  Id:"))
        self.assertIn("sample!leaf", self.s.ok("~ * kc"))

    def test_dv(self):
        self.assertIn("v = 0n8", self.s.ok("dv"))
        self.assertIn("int v = 0n8", self.s.ok("dv /t"))


class SymbolsTest(SessionTest):
    def test_lm(self):
        out = self.s.lines("lm")
        self.assertTrue(out[0].startswith("start"))
        self.assertTrue(any(" sample " in l for l in out))
        self.assertIn("Image path:", self.s.ok("lmvm sample"))

    def test_x(self):
        out = self.s.ok("x sample!g_*")
        self.assertIn("sample!g_magic = 0xfeedface", out)
        self.assertIn('sample!g_ascii = [16] "Hello, WinLLDB!"', out)
        self.assertIn("sample!leaf (int)", self.s.ok("x /f sample!le*"))
        self.assertIn("v = 0n8", self.s.ok("x *"))

    def test_ln(self):
        out = self.s.ok("ln leaf+3")
        self.assertIn("sample!leaf+0x3", out)
        self.assertIn("sample!middle", out)
        self.assertIn("Exact matches:", self.s.ok("ln leaf"))

    def test_search(self):
        self.assertIn("WinLLDB!", self.s.ok('s -a g_ascii L20 "WinLLDB"'))
        self.assertIn("73 00 74 00", self.s.ok('s -u g_wide L20 "string"'))
        self.assertIn("03 04 05", self.s.ok("s -b g_bytes L20 03 04 05"))
        self.assertIn("feedface", self.s.ok("s -d g_magic L4 feedface"))
        self.assertEqual(self.s.ok("s -b g_bytes L20 ff ee").strip(), "")

    def test_eval(self):
        self.assertIn("Evaluate expression: 16 = 00000000`00000010", self.s.ok("? 10"))
        self.assertIn("Evaluate expression: -1 = ffffffff`ffffffff", self.s.ok("? -1"))
        self.assertIn("= 6", self.s.ok("?? g_sample.a + 1"))
        self.assertIn("Couldn't resolve", self.s.fail("? nosuchsym"))


class ExecutionTest(unittest.TestCase):
    def setUp(self):
        self.s = Session("middle")

    def tearDown(self):
        self.s.close()

    def site(self):
        return self.s.lines("kc 1")[1]

    def test_step_and_go_up(self):
        self.s.ok("p")
        self.assertIn("@ 38]", self.site())
        self.s.ok("t")
        self.assertIn("sample!leaf", self.site())
        self.s.ok("gu")
        self.assertIn("sample!middle", self.site())

    def test_pt_stops_at_ret(self):
        self.s.ok("pt")
        self.assertIn("ret", self.s.lines("u @rip L1")[1])

    def test_g_to_address_and_exit(self):
        self.s.ok("g leaf")
        self.assertIn("sample!leaf", self.site())
        self.assertFalse(any("@ 31]" in l and "e " in l for l in self.s.lines("bl")[1:]))
        self.s.ok("bc *")
        self.assertIn("exited", self.s.ok("g"))


if __name__ == "__main__":
    unittest.main()
