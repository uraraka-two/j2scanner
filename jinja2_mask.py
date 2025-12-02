#!/usr/bin/env python3
# jinja2_mask.py
#
# jinja2 構文 ({{ }}, {% %}, {# #}) を self-contained プレースホルダに置き換え、
# 後で元に戻すためのツール。
#
# ここでは Jinja 構文検出に .*? の正規表現は使わず、
# str.find による手書きスキャナで {{ / {% / {# をたどっていく。
#
# プレースホルダ形式:
#   __J2OMIT_<KIND>_<LEN>_<HEX>__
#   KIND: E (expr), S (stmt), C (comment)
#   LEN : 元スニペットの UTF-8 バイト長 (10進)
#   HEX : 元スニペットの UTF-8 バイト列を16進化した文字列
#
# 例:
#   {{ brokers | join(",") }}
#   => __J2OMIT_E_27_7b7b2062726f6b657273207c206a6f696e28222c2229207d7d__
#
# 依存: Python3 標準ライブラリのみ

import sys
import re


# ========= プレースホルダ encode/decode =========

PH_RE = re.compile(r"__J2OMIT_([ESC])_(\d+)_([0-9a-fA-F]+)__")

def encode_placeholder(kind: str, snippet: str) -> str:
    raw = snippet.encode("utf-8")
    length = len(raw)
    hex_str = raw.hex()
    return f"__J2OMIT_{kind}_{length}_{hex_str}__"

def decode_placeholder(kind: str, length_str: str, hex_str: str) -> str:
    raw = bytes.fromhex(hex_str)
    length = int(length_str)
    if length != len(raw):
        raise ValueError(f"length mismatch in placeholder: len={length}, actual={len(raw)}")
    return raw.decode("utf-8")


# ========= ユーティリティ =========

def last_line_start(s: str, i: int) -> int:
    """位置 i の属する行の先頭インデックスを返す"""
    j = s.rfind("\n", 0, i)
    if j < 0:
        return 0
    return j + 1

def next_line_end(s: str, i: int) -> tuple[int, bool]:
    """位置 i から見た次の改行の位置と、改行があったかどうか"""
    if i >= len(s):
        return len(s), False
    j = s.find("\n", i)
    if j < 0:
        return len(s), False
    return j, True

def leading_indent(line: str) -> str:
    out = []
    for ch in line:
        if ch in (" ", "\t"):
            out.append(ch)
        else:
            break
    return "".join(out)


# ========= mask 本体（Jinja 構文検出は手書きスキャナ） =========

def mask_text(s: str) -> str:
    out = []
    pos = 0
    n = len(s)
    inside_raw = False

    while pos < n:
        # 次の {{, {%, {# を探す
        idx_expr = s.find("{{", pos)
        idx_stmt = s.find("{%", pos)
        idx_comm = s.find("{#", pos)

        if inside_raw:
            # raw ブロック内は {{ と {# を無視
            idx_expr = -1
            idx_comm = -1

        # 一番手前のトークンを選ぶ
        min_pos = -1
        tag = None
        for idx, t in ((idx_expr, "{{"), (idx_stmt, "{%"), (idx_comm, "{#")):
            if idx != -1 and (min_pos == -1 or idx < min_pos):
                min_pos = idx
                tag = t

        if min_pos == -1:
            # もうトークンがない
            out.append(s[pos:])
            break

        if tag == "{{":
            end = s.find("}}", min_pos + 2)
            if end == -1:
                # 閉じがなければ残り全部そのまま
                out.append(s[pos:])
                break
            # 先頭〜トークン直前
            out.append(s[pos:min_pos])
            snippet = s[min_pos:end + 2]
            out.append(encode_placeholder("E", snippet))
            pos = end + 2

        elif tag == "{%":
            end = s.find("%}", min_pos + 2)
            if end == -1:
                out.append(s[pos:])
                break

            snippet = s[min_pos:end + 2]

            # 行境界を取る（行コメント化のため）
            ls = last_line_start(s, min_pos)
            le, had_nl = next_line_end(s, end + 2)
            line = s[ls:le]
            indent = leading_indent(line)

            # 行全体をコメントで置き換える
            out.append(s[pos:ls])
            ph = encode_placeholder("S", snippet)
            out.append(indent + "# " + ph)
            if had_nl:
                out.append("\n")
            pos = le

            # raw / endraw の出入り管理
            inner = s[min_pos+2:end].strip().lower()
            if inside_raw:
                if inner.startswith("endraw"):
                    inside_raw = False
            else:
                if inner == "raw" or inner.startswith("raw "):
                    inside_raw = True

        elif tag == "{#":
            end = s.find("#}", min_pos + 2)
            if end == -1:
                out.append(s[pos:])
                break

            snippet = s[min_pos:end + 2]
            ls = last_line_start(s, min_pos)
            le, had_nl = next_line_end(s, end + 2)
            line = s[ls:le]
            indent = leading_indent(line)

            out.append(s[pos:ls])
            ph = encode_placeholder("C", snippet)
            out.append(indent + "# " + ph)
            if had_nl:
                out.append("\n")
            pos = le

    return "".join(out)


# ========= unmask 本体（プレースホルダだけ正規表現で検出） =========

def unmask_text(s: str, strict: bool = False) -> str:
    def repl_line(m: re.Match) -> str:
        kind, length_str, hex_str = m.groups()
        try:
            return decode_placeholder(kind, length_str, hex_str)
        except Exception as e:
            if strict:
                raise
            sys.stderr.write(f"[WARN] invalid placeholder ignored: {m.group(0)} ({e})\n")
            return m.group(0)

    out_lines = []
    for line in s.splitlines(keepends=True):
        # 行丸ごとコメントのパターン: 先頭に「# __J2OMIT_...__」
        m_full = re.match(r"^(\s*)#\s*(__J2OMIT_[ESC]_\d+_[0-9a-fA-F]+__)\s*$", line)
        if m_full:
            indent, token = m_full.groups()
            m = PH_RE.fullmatch(token)
            if m:
                restored = repl_line(m)
                out_lines.append(indent + restored + "\n")
                continue
            else:
                out_lines.append(line)
                continue

        # インラインの E/S/C もまとめて置換
        def repl_inline(m: re.Match) -> str:
            return repl_line(m)

        out_lines.append(PH_RE.sub(repl_inline, line))

    return "".join(out_lines)


# ========= CLI =========

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("mask", "unmask"):
        print("Usage: jinja2_mask.py mask|unmask [FILE or -]", file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[1]
    if len(sys.argv) >= 3 and sys.argv[2] != "-":
        with open(sys.argv[2], "r", encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    if mode == "mask":
        out = mask_text(text)
    else:
        out = unmask_text(text)

    sys.stdout.write(out)


if __name__ == "__main__":
    main()
