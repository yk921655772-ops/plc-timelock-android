# calculator.py — PLC 时间锁授权工具 公式解析器核心类
import ast
import math
import re
from typing import Tuple


# 允许在公式中使用的安全内置函数
SAFE_BUILTINS = {
    "abs": abs,
    "int": int,
    "round": round,
    "pow": pow,
    "min": min,
    "max": max,
}

SAFE_MATH = {
    "sin": math.sin,
    "cos": math.cos,
    "sqrt": math.sqrt,
    "floor": math.floor,
    "ceil": math.ceil,
    "pi": math.pi,
}

# AST 节点白名单（允许的语法结构）
ALLOWED_AST_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
    ast.Mod, ast.Pow,
    ast.BitAnd, ast.BitOr, ast.BitXor,
    ast.LShift, ast.RShift,
    ast.Invert, ast.UAdd, ast.USub,
    ast.Call,
    ast.Attribute,
)


class FormulaCalculator:
    """
    安全公式计算器。
    支持变量: Y(年), M(月), D(日), H(小时), MC(机器码整数)
    支持运算: + - * / // % ^ & | ( )
    支持函数: abs, int, round, pow, min, max, sin, cos, sqrt, floor, ceil
    """

    def __init__(self):
        self._formula: str = "(Y + M + D) * MC"

    def set_formula(self, formula: str):
        """设置公式"""
        self._formula = formula.strip()

    def get_formula(self) -> str:
        return self._formula

    def validate(self, formula: str) -> Tuple[bool, str]:
        """
        使用 ast 模块做安全语法检查。
        返回: (是否合法, 错误信息)
        """
        formula = formula.strip()
        if not formula:
            return False, "公式不能为空"

        try:
            tree = ast.parse(formula, mode="eval")
        except SyntaxError as e:
            return False, f"语法错误: {e.msg}（第 {e.lineno} 列 {e.offset}）"

        # 遍历 AST 节点，检查是否有不允许的结构
        for node in ast.walk(tree):
            if not isinstance(node, ALLOWED_AST_NODES):
                return False, f"不允许的语法结构: {type(node).__name__}"

            # 函数调用只允许白名单中的函数
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    if func.id not in SAFE_BUILTINS:
                        return False, f"不允许的函数: {func.id}()"
                elif isinstance(func, ast.Attribute):
                    # 允许 sin/cos 等作为独立名称（通过 Name 调用）
                    if func.attr not in SAFE_MATH:
                        return False, f"不允许的方法: {func.attr}()"
                else:
                    return False, "不允许的函数调用形式"

        return True, "公式语法正确"

    @staticmethod
    def parse_machine_code(mc_str: str, mode: str = "hex") -> int:
        """
        解析机器码为整数。
        mode="hex": 将机器码视为十六进制数，转换为十进制整数
        mode="ascii": 将每个字符的 ASCII 码求和
        """
        mc_str = mc_str.upper().strip()
        if not mc_str:
            return 0

        if mode == "hex":
            try:
                return int(mc_str, 16)
            except ValueError:
                # 如果不是合法的十六进制，改用 ASCII 求和
                return sum(ord(c) for c in mc_str)
        else:  # ascii
            return sum(ord(c) for c in mc_str)

    def calculate(self, Y: int, M: int, D: int, H: int,
                  mc_str: str, mc_mode: str = "hex") -> Tuple[str, str]:
        """
        执行公式计算。
        返回: (6位密码字符串, 错误信息)
        错误时密码字符串为空。
        """
        valid, err_msg = self.validate(self._formula)
        if not valid:
            return "", err_msg

        MC = self.parse_machine_code(mc_str, mc_mode)

        # 构建安全的执行环境
        safe_globals = {"__builtins__": {}}
        safe_globals.update(SAFE_BUILTINS)
        # 将 math 函数平铺进去，允许直接调用 sin(), cos() 等
        safe_globals.update(SAFE_MATH)

        safe_locals = {
            "Y": Y,
            "M": M,
            "D": D,
            "H": H,
            "MC": MC,
        }

        try:
            result = eval(self._formula, safe_globals, safe_locals)  # noqa: S307
            result = int(abs(float(result))) % 1_000_000
            return f"{result:06d}", ""
        except ZeroDivisionError:
            return "", "计算错误: 除数不能为零"
        except OverflowError:
            return "", "计算错误: 数值溢出"
        except Exception as e:
            return "", f"计算错误: {e}"


# ---------- 预设公式模板 ----------
PRESET_TEMPLATES = [
    {
        "name": "简单模式",
        "formula": "(Y + M + D) * MC",
        "description": "年月日之和乘以机器码",
    },
    {
        "name": "中等模式",
        "formula": "(Y ^ M) + (D * 1000) + (H * 100) + (MC % 1000)",
        "description": "年月异或 + 日期权重 + 小时权重 + 机器码取模",
    },
    {
        "name": "复杂模式",
        "formula": "((Y * 31 + M) * 37 + D) ^ MC + H * 7",
        "description": "多项式混合 + 异或 + 小时加权",
    },
    {
        "name": "位运算模式",
        "formula": "(Y & MC) | (M * D) ^ (H * 13 + 7)",
        "description": "位与、位或、异或混合运算",
    },
]
