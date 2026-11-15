import unittest

from tests.unit.fakes import FakeResolver
from winlldb import expr
from winlldb.registry import WinDbgError

MASK = (1 << 64) - 1


def mem_qword(a, v):
    return {a + i: (v >> (8 * i)) & 0xFF for i in range(8)}


class ExprTest(unittest.TestCase):
    def setUp(self):
        self.res = FakeResolver(
            registers={"rax": 0x10, "rsp": 0x1000},
            symbols={"sample!main": 0x401000, "foo": 0x2000, "libc.so.6!malloc": 0x7000, "ld-linux!start": 0x9000},
            memory=mem_qword(0x1000, 0x1122334455667788),
            pseudo={"ip": 0x401010},
        )

    def ev(self, text):
        return expr.evaluate(text, self.res)

    def test_numbers_default_to_hex(self):
        self.assertEqual(self.ev("10"), 0x10)
        self.assertEqual(self.ev("deadbeef"), 0xDEADBEEF)
        self.assertEqual(self.ev("0x10"), 0x10)
        self.assertEqual(self.ev("0n10"), 10)
        self.assertEqual(self.ev("0y101"), 5)
        self.assertEqual(self.ev("10h"), 0x10)
        self.assertEqual(self.ev("7ff7`1a3b1000"), 0x7FF71A3B1000)

    def test_arithmetic(self):
        self.assertEqual(self.ev("(1+2)*3"), 9)
        self.assertEqual(self.ev("1+2*3"), 7)
        self.assertEqual(self.ev("1 << 4"), 0x10)
        self.assertEqual(self.ev("ff & f0 | 1"), 0xF1)
        self.assertEqual(self.ev("-1"), MASK)
        self.assertEqual(self.ev("20 / 3"), 0xA)
        self.assertEqual(self.ev("20 % 3"), 2)

    def test_divide_by_zero(self):
        with self.assertRaises(WinDbgError):
            self.ev("8/0")

    def test_registers_and_pseudo(self):
        self.assertEqual(self.ev("@rax+8"), 0x18)
        self.assertEqual(self.ev("rax"), 0x10)
        self.assertEqual(self.ev("@$ip"), 0x401010)
        self.assertEqual(self.ev("$ip-10"), 0x401000)
        with self.assertRaises(WinDbgError):
            self.ev("@nosuch")

    def test_symbols(self):
        self.assertEqual(self.ev("sample!main+0x10"), 0x401010)
        self.assertEqual(self.ev("foo"), 0x2000)
        self.assertEqual(self.ev("libc.so.6!malloc"), 0x7000)
        self.assertEqual(self.ev("ld-linux!start+1"), 0x9001)
        with self.assertRaises(WinDbgError):
            self.ev("nosuch")

    def test_memory_functions(self):
        self.assertEqual(self.ev("poi(@rsp)"), 0x1122334455667788)
        self.assertEqual(self.ev("dwo(@rsp)"), 0x55667788)
        self.assertEqual(self.ev("wo(@rsp)"), 0x7788)
        self.assertEqual(self.ev("by(@rsp+1)"), 0x77)
        self.assertEqual(self.ev("qwo(1000)"), 0x1122334455667788)

    def test_syntax_errors(self):
        for bad in ("", "1 +", "(1", "1 2", "#"):
            with self.subTest(bad=bad), self.assertRaises(WinDbgError):
                self.ev(bad)

    def test_is_symbol_name(self):
        self.assertTrue(expr.is_symbol_name("foo"))
        self.assertTrue(expr.is_symbol_name("sample!ns::foo"))
        self.assertFalse(expr.is_symbol_name("foo+4"))
        self.assertFalse(expr.is_symbol_name("@rip"))
        self.assertFalse(expr.is_symbol_name("401000"))
        self.assertFalse(expr.is_symbol_name("cafe"))


if __name__ == "__main__":
    unittest.main()
