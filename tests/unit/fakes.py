from winlldb import expr


class FakeResolver:
    ptrsize = 8
    byteorder = "little"

    def __init__(self, registers=None, symbols=None, memory=None, pseudo=None):
        self.registers = registers or {}
        self.symbols = symbols or {}
        self.memory = memory or {}
        self.pseudo = pseudo or {}

    def register_value(self, name, quiet=False):
        return self.registers.get(name)

    def pseudo_value(self, name):
        return self.pseudo[name]

    def symbol_address(self, name):
        return self.symbols.get(name)

    def read_uint(self, a, size):
        return int.from_bytes(bytes(self.memory.get(a + i, 0) for i in range(size)), "little")

    def eval(self, text):
        return expr.evaluate(text, self)
