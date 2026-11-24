"""表达式形态：把作者写的公式解析成算子调用。

为什么要有它：口径作者写 "sum(amount, where=direction=='out')" 比堆一串 JSON 步骤快得多。
但它不能变成第二套语义，所以这里只负责「分词 + 优先级 + 求值顺序」，
每个语法成分最后都落到 operators.invoke() 上——同一个算子、同一份值语义。

语法子集（完整 BNF 见 README）：
    expr    := ternary
    ternary := or_expr [ "if" or_expr "else" ternary ]
    or_expr := and_expr { "or" and_expr }
    and_expr:= not_expr { "and" not_expr }
    not_expr:= "not" not_expr | compare
    compare := additive [ ("=="|"!="|">="|"<="|">"|"<") additive ]
    additive:= multiplicative { ("+"|"-") multiplicative }
    multiplicative := unary { ("*"|"/") unary }
    unary   := ("-"|"+") unary | primary
    primary := NUMBER | STRING | true | false | none | null
             | NAME "(" [args] ")"          # 函数调用 = 算子调用
             | NAME                         # 列引用 = 一列值，与行对齐
             | "(" expr ")"
    args    := arg { "," arg }
    arg     := [ NAME "=" ] expr
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from . import operators as ops
from .operators import Frame, OperatorError

# 表达式里的别名：写成大家习惯的样子，落地仍是同一个算子
_CALL_ALIASES = {"len": "count", "length": "count", "if": "if_else", "avg": "mean"}
_BIN_OPS = {
    "==": "eq", "!=": "ne", ">=": "ge", "<=": "le", ">": "gt", "<": "lt",
    "+": "add", "-": "sub", "*": "mul", "/": "div",
    "and": "and", "or": "or",
}
_KEYWORDS = {"and", "or", "not", "if", "else", "true", "false", "none", "null"}

_NAME = re.compile(r"[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_TWO_CHAR = ("==", "!=", ">=", "<=")
_ONE_CHAR = "()+-*/,<>="


class ExprError(ValueError):
    """表达式写错了：消息里带出错位置、原文和指针，作者不必猜。"""


class Token:
    __slots__ = ("kind", "text", "pos")

    def __init__(self, kind: str, text: str, pos: int):
        self.kind = kind
        self.text = text
        self.pos = pos

    def __repr__(self) -> str:
        return f"Token({self.kind},{self.text!r})"


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
            continue
        matched = _NUMBER.match(text, index)
        if matched:
            tokens.append(Token("number", matched.group(0), index))
            index = matched.end()
            continue
        if char in "'\"":
            end = text.find(char, index + 1)
            if end < 0:
                raise ExprError(f"表达式语法错误（第 {index + 1} 字符）：字符串没有收尾的 {char}\n{text}")
            tokens.append(Token("string", text[index + 1:end], index))
            index = end + 1
            continue
        matched = _NAME.match(text, index)
        if matched:
            word = matched.group(0)
            kind = "keyword" if word in _KEYWORDS else "name"
            tokens.append(Token(kind, word, index))
            index = matched.end()
            continue
        pair = text[index:index + 2]
        if pair in _TWO_CHAR:
            tokens.append(Token("op", pair, index))
            index += 2
            continue
        if char in _ONE_CHAR:
            tokens.append(Token("op", char, index))
            index += 1
            continue
        raise ExprError(f"表达式语法错误（第 {index + 1} 字符）：认不出的字符 {char!r}\n{text}")
    tokens.append(Token("eof", "", len(text)))
    return tokens


class Parser:
    def __init__(self, text: str):
        self.text = text
        self.tokens = tokenize(text)
        self.index = 0

    # ---- 基础 ----
    def peek(self) -> Token:
        return self.tokens[self.index]

    def advance(self) -> Token:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def look(self, text: str) -> bool:
        token = self.peek()
        return token.kind in ("op", "keyword", "name") and token.text == text

    def accept(self, text: str) -> bool:
        if self.look(text):
            self.advance()
            return True
        return False

    def fail(self, message: str, token: Token | None = None) -> None:
        token = token or self.peek()
        pointer = " " * token.pos + "^"
        raise ExprError(
            f"表达式语法错误（第 {token.pos + 1} 字符）：{message}\n{self.text}\n{pointer}"
        )

    def expect(self, text: str) -> Token:
        if not self.look(text):
            self.fail(f"期望 {text!r}，实际是 {self.peek().text!r}")
        return self.advance()

    # ---- 文法 ----
    def parse(self) -> tuple:
        if self.peek().kind == "eof":
            self.fail("表达式是空的")
        node = self.ternary()
        if self.peek().kind != "eof":
            self.fail(f"多余的内容 {self.peek().text!r}")
        return node

    def ternary(self) -> tuple:
        node = self.or_expr()
        if self.accept("if"):
            cond = self.or_expr()
            self.expect("else")
            other = self.ternary()
            return ("call", "if_else", [cond, node, other], {})
        return node

    def or_expr(self) -> tuple:
        node = self.and_expr()
        while self.look("or"):
            self.advance()
            node = ("bin", _BIN_OPS["or"], node, self.and_expr())
        return node

    def and_expr(self) -> tuple:
        node = self.not_expr()
        while self.look("and"):
            self.advance()
            node = ("bin", _BIN_OPS["and"], node, self.not_expr())
        return node

    def not_expr(self) -> tuple:
        if self.look("not"):
            self.advance()
            return ("call", "not", [self.not_expr()], {})
        return self.compare()

    def compare(self) -> tuple:
        node = self.additive()
        token = self.peek()
        if token.kind == "op" and token.text in _BIN_OPS and token.text in ("==", "!=", ">=", "<=", ">", "<"):
            self.advance()
            node = ("bin", _BIN_OPS[token.text], node, self.additive())
            if self.peek().kind == "op" and self.peek().text in ("==", "!=", ">=", "<=", ">", "<"):
                self.fail("不支持链式比较，请用 and 拆成两次比较")
        return node

    def additive(self) -> tuple:
        node = self.multiplicative()
        while True:
            token = self.peek()
            if token.kind == "op" and token.text in ("+", "-"):
                self.advance()
                node = ("bin", _BIN_OPS[token.text], node, self.multiplicative())
            else:
                return node

    def multiplicative(self) -> tuple:
        node = self.unary()
        while True:
            token = self.peek()
            if token.kind == "op" and token.text in ("*", "/"):
                self.advance()
                node = ("bin", _BIN_OPS[token.text], node, self.unary())
            else:
                return node

    def unary(self) -> tuple:
        if self.accept("-"):
            return ("call", "neg", [self.unary()], {})
        if self.accept("+"):
            return self.unary()
        return self.primary()

    def primary(self) -> tuple:
        token = self.peek()
        if token.kind == "number":
            self.advance()
            try:
                return ("num", Decimal(token.text))
            except InvalidOperation:
                self.fail(f"数字写错了：{token.text!r}", token)
        if token.kind == "string":
            self.advance()
            return ("str", token.text)
        if token.kind == "keyword":
            if token.text == "true":
                self.advance()
                return ("bool", True)
            if token.text == "false":
                self.advance()
                return ("bool", False)
            if token.text in ("none", "null"):
                self.advance()
                return ("null",)
        if token.kind == "name":
            self.advance()
            if self.accept("("):
                positional, keyword = self.arguments()
                return ("call", token.text, positional, keyword)
            return ("col", token.text)
        if self.accept("("):
            node = self.ternary()
            self.expect(")")
            return node
        self.fail(f"认不出的开头 {token.text!r}")

    def arguments(self) -> tuple[list[tuple], dict[str, tuple]]:
        positional: list[tuple] = []
        keyword: dict[str, tuple] = {}
        if self.accept(")"):
            return positional, keyword
        while True:
            token = self.peek()
            if token.kind == "name" and self.tokens[self.index + 1].text == "=":
                self.advance()
                self.advance()
                keyword[token.text] = self.ternary()
            else:
                if keyword:
                    self.fail("位置参数不能写在关键字参数之后")
                positional.append(self.ternary())
            if self.accept(","):
                continue
            self.expect(")")
            return positional, keyword


_TREES: dict[str, tuple] = {}


def parse(text: str) -> tuple:
    """解析并缓存语法树：同一段公式在每次计算时都会重复使用。"""
    if not isinstance(text, str) or not text.strip():
        raise ExprError("表达式不能为空")
    tree = _TREES.get(text)
    if tree is None:
        tree = Parser(text).parse()
        _TREES[text] = tree
    return tree


def _eval_callee(name: str, positional: list[tuple], keyword: dict[str, tuple],
                 frame: Frame, notes: list[str] | None) -> tuple[str, list[Any], dict[str, Any]]:
    key = _CALL_ALIASES.get(name, name)
    spec = ops.spec_of(key)
    evaluated: list[Any] = []
    for index, node in enumerate(positional):
        if index == 0 and spec.key_first:
            if node[0] == "col":
                evaluated.append(node[1])
                continue
            if node[0] == "str":
                evaluated.append(node[1])
                continue
            raise OperatorError(
                f"算子 {key} 的第一个参数必须是列名（例如 {key}(counterparty_name) 或 {key}('counterparty_name')）"
            )
        evaluated.append(_eval(node, frame, notes))
    values = {name_: _eval(node, frame, notes) for name_, node in keyword.items()}
    return key, evaluated, values


def _eval(node: tuple, frame: Frame, notes: list[str] | None) -> Any:
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "str":
        return node[1]
    if kind == "bool":
        return node[1]
    if kind == "null":
        return None
    if kind == "col":
        return ops.column(frame, node[1])
    if kind == "bin":
        left = _eval(node[2], frame, notes)
        right = _eval(node[3], frame, notes)
        return ops.invoke(node[1], left, right, notes=notes)
    if kind == "call":
        key, positional, keyword = _eval_callee(node[1], node[2], node[3], frame, notes)
        return ops.invoke_for_expr(key, frame, positional, keyword, notes=notes)
    raise ExprError(f"语法树里有认不出的节点：{kind!r}")


def eval_expr(text: str, frame: Frame, *, notes: list[str] | None = None) -> Any:
    """求值：返回数值/布尔/表/序列；缺失按算子语义得到 None。"""
    return _eval(parse(text), frame, notes)

