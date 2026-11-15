import unittest

from tests.unit.fakes import FakeResolver
from winlldb import args, fmt
from winlldb.registry import WinDbgError


class SplitTest(unittest.TestCase):
    def test_split_keeps_groups(self):
        self.assertEqual(args.split('bp poi(@rsp + 8) "k; g"'), ["bp", "poi(@rsp + 8)", '"k; g"'])
        self.assertEqual(args.split("  db  @rsp   L10 "), ["db", "@rsp", "L10"])

    def test_unterminated_string(self):
        with self.assertRaises(WinDbgError):
            args.split('s -a 0 L10 "abc')

    def test_unquote(self):
        self.assertEqual(args.unquote('"abc"'), "abc")
        self.assertEqual(args.unquote("abc"), "abc")


class RangeTest(unittest.TestCase):
    def setUp(self):
        self.ctx = FakeResolver(symbols={"foo": 0x2000})

    def parse(self, text, default=8, elem=1, **kw):
        return args.parse_range(self.ctx, args.split(text), default, elem, **kw)

    def test_empty(self):
        r = self.parse("")
        self.assertIsNone(r.start)
        self.assertEqual(r.count, 8)

    def test_count_forms(self):
        self.assertEqual(self.parse("1000 L10").count, 0x10)
        self.assertEqual(self.parse("1000 L 10").count, 0x10)
        self.assertEqual(self.parse("1000 l0n20").count, 20)
        self.assertTrue(self.parse("1000 L?20000000").explicit)

    def test_count_without_address(self):
        r = self.parse("L4")
        self.assertIsNone(r.start)
        self.assertEqual(r.count, 4)

    def test_range_limit(self):
        with self.assertRaises(WinDbgError):
            self.parse("1000 L20000000")

    def test_end_address_inclusive(self):
        r = self.parse("1000 100f", elem=4)
        self.assertEqual(r.count, 4)
        with self.assertRaises(WinDbgError):
            self.parse("1000 f00")

    def test_rest(self):
        r = self.parse('foo L10 "pattern" x')
        self.assertEqual((r.start, r.count, r.rest), (0x2000, 0x10, ['"pattern"', "x"]))
        r = self.parse("foo bar", allow_end=False)
        self.assertEqual(r.rest, ["bar"])


class FmtTest(unittest.TestCase):
    def test_addr(self):
        self.assertEqual(fmt.addr(0x7FF71A3B1000), "00007ff7`1a3b1000")
        self.assertEqual(fmt.addr(0x401000, 4), "00401000")
        self.assertEqual(fmt.addr(-1), "ffffffff`ffffffff")

    def test_strip_params(self):
        self.assertEqual(fmt.strip_params("ns::foo(int, char*)"), "ns::foo")
        self.assertEqual(fmt.strip_params("foo(void (*)(int))"), "foo")
        self.assertEqual(fmt.strip_params("Foo::bar() const"), "Foo::bar")
        self.assertEqual(fmt.strip_params("main"), "main")
        self.assertEqual(fmt.strip_params("Foo::operator()"), "Foo::operator()")

    def test_hexdump_line(self):
        line = fmt.hexdump_line(0x1000, list(range(0x41, 0x51)), 8)
        self.assertEqual(line, "00000000`00001000  41 42 43 44 45 46 47 48-49 4a 4b 4c 4d 4e 4f 50  ABCDEFGHIJKLMNOP")
        partial = fmt.hexdump_line(0x1000, [0x00, None], 4)
        self.assertTrue(partial.startswith("00001000  00 ??"))
        self.assertTrue(partial.endswith(".?"))


if __name__ == "__main__":
    unittest.main()
