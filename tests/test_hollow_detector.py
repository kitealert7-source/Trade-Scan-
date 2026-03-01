"""Quick test for HollowDetector in semantic_validator.py"""
import ast
import sys
import unittest


# Hollow template (matches provisioner output)
HOLLOW = '''
class Strategy:
    def check_entry(self, ctx):
        """Return entry signal dict or None."""
        if not self.filter_stack.allow_trade(ctx):
            return None
        return None
'''

# Implemented strategy (has actual logic)
REAL = '''
class Strategy:
    def check_entry(self, ctx):
        """Return entry signal dict or None."""
        if not self.filter_stack.allow_trade(ctx):
            return None
        row = ctx["row"]
        if row["close"] > 1.0:
            return {"signal": 1}
        return None
'''


class HollowDetector(ast.NodeVisitor):
    def __init__(self):
        self.check_entry_is_hollow = False

    def visit_FunctionDef(self, node):
        if node.name != "check_entry":
            return
        remaining = []
        for stmt in node.body:
            if isinstance(stmt, ast.Expr) and isinstance(
                getattr(stmt, 'value', None), (ast.Constant, ast.Str)
            ):
                continue
            if isinstance(stmt, ast.If):
                test = stmt.test
                is_guard = False
                if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
                    call = test.operand
                    if (isinstance(call, ast.Call) and
                        isinstance(call.func, ast.Attribute) and
                        call.func.attr == "allow_trade"):
                        is_guard = True
                if is_guard:
                    continue
            if isinstance(stmt, ast.Return):
                val = stmt.value
                if val is None or (isinstance(val, ast.Constant) and val.value is None):
                    continue
            remaining.append(stmt)
        if len(remaining) == 0:
            self.check_entry_is_hollow = True


class TestHollowDetector(unittest.TestCase):
    """Test 1 -- Hollow template is correctly detected."""

    def test_hollow_detected(self):
        h = HollowDetector()
        h.visit(ast.parse(HOLLOW))
        self.assertTrue(
            h.check_entry_is_hollow,
            "Hollow template should be detected as hollow"
        )

    def test_real_strategy_not_hollow(self):
        """Test 2 -- Real strategy is NOT flagged as hollow."""
        r = HollowDetector()
        r.visit(ast.parse(REAL))
        self.assertFalse(
            r.check_entry_is_hollow,
            "Real strategy should not be flagged as hollow"
        )


if __name__ == "__main__":
    unittest.main()
