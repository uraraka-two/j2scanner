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
import os
from pathlib import Path
from typing import Callable, Optional


# ========= プレースホルダ encode/decode =========

# 16進数形式: __J2OMIT_E_27_7b7b2062726f6b657273207d7d__
PH_RE_HEX = re.compile(r"__J2OMIT_([ESCRB])_(\d+)_([0-9a-fA-F]+)__")

# Base26形式: __J2E_B26:ABCDEF__
PH_RE_B26 = re.compile(r"__J2([ESCRB])_B26:([A-Z]+)__")

# Base26 encode/decode
def encode_b26(data: bytes) -> str:
    """バイト列をBase26エンコード (A-Z のみ使用)"""
    return "".join(chr(65 + b // 26) + chr(65 + b % 26) for b in data)

def decode_b26(text: str) -> bytes:
    """Base26文字列をバイト列にデコード"""
    if len(text) % 2:
        raise ValueError("B26: odd length")
    out = bytearray(len(text) // 2)
    for i in range(0, len(text), 2):
        hi = ord(text[i]) - 65
        lo = ord(text[i + 1]) - 65
        if not (0 <= hi < 26 and 0 <= lo < 26):
            raise ValueError("B26: non-uppercase letter detected")
        out[i // 2] = hi * 26 + lo
    return bytes(out)

# プレースホルダ生成 (エンコーディング方式により切り替え)
def encode_placeholder(kind: str, snippet: str, use_b26: bool = False) -> str:
    """プレースホルダを生成"""
    if use_b26:
        # Base26形式: __J2E_B26:ABCDEF__
        raw = snippet.encode("utf-8")
        b26_str = encode_b26(raw)
        return f"__J2{kind}_B26:{b26_str}__"
    else:
        # 16進数形式: __J2OMIT_E_27_7b7b2062726f6b657273207d7d__
        raw = snippet.encode("utf-8")
        length = len(raw)
        hex_str = raw.hex()
        return f"__J2OMIT_{kind}_{length}_{hex_str}__"

def decode_placeholder_hex(kind: str, length_str: str, hex_str: str) -> str:
    """16進数形式のプレースホルダをデコード"""
    raw = bytes.fromhex(hex_str)
    length = int(length_str)
    if length != len(raw):
        raise ValueError(f"length mismatch in placeholder: len={length}, actual={len(raw)}")
    return raw.decode("utf-8")

def decode_placeholder_b26(kind: str, b26_str: str) -> str:
    """Base26形式のプレースホルダをデコード"""
    raw = decode_b26(b26_str)
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

# バックスラッシュを含む文字列リテラルを検出
BACKSLASH_STR = re.compile(r'"(?:[^"\\]|\\.)*"')

def mask_text(s: str, use_b26: bool = False, allow_inline: bool = True, protect_backslash: bool = True) -> str:
    """
    Jinja2構文をプレースホルダに置き換える

    Args:
        s: 入力テキスト
        use_b26: Base26エンコーディングを使用するか (デフォルト: False = 16進数)
        allow_inline: {% %} の行内配置を許可するか (デフォルト: True)
        protect_backslash: バックスラッシュ文字列を保護するか (デフォルト: True)
    """
    # バックスラッシュ文字列の保護
    if protect_backslash:
        def protect_bs(m: re.Match) -> str:
            if "\\" in m.group(0):
                return encode_placeholder("B", m.group(0), use_b26)
            return m.group(0)
        s = BACKSLASH_STR.sub(protect_bs, s)

    out = []
    pos = 0
    n = len(s)
    inside_raw = False

    while pos < n:
        # 次の {{, {%, {#, #{ を探す
        idx_expr = s.find("{{", pos)
        idx_stmt = s.find("{%", pos)
        idx_comm = s.find("{#", pos)
        idx_ruby = s.find("#{", pos)  # Ruby style interpolation

        if inside_raw:
            # raw ブロック内は {{ と {# と #{ を無視
            idx_expr = -1
            idx_comm = -1
            idx_ruby = -1

        # 一番手前のトークンを選ぶ
        min_pos = -1
        tag = None
        for idx, t in ((idx_expr, "{{"), (idx_stmt, "{%"), (idx_comm, "{#"), (idx_ruby, "#{")):
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
            out.append(encode_placeholder("E", snippet, use_b26))
            pos = end + 2

        elif tag == "#{":
            # Ruby style interpolation
            end = s.find("}", min_pos + 2)
            if end == -1:
                out.append(s[pos:])
                break
            out.append(s[pos:min_pos])
            snippet = s[min_pos:end + 1]
            out.append(encode_placeholder("R", snippet, use_b26))
            pos = end + 1

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

            # 行内に他のコンテンツがあるかチェック
            left = s[ls:min_pos].strip()
            right = s[end + 2:le].strip()

            if (left or right) and not allow_inline:
                # インライン配置が禁止されている場合はエラー
                snippet_display = line.rstrip("\r\n")
                raise ValueError(f"行内に {{% ... %}} が混在: {snippet_display}")

            indent = leading_indent(line)

            # 行全体をコメントで置き換える
            out.append(s[pos:ls])
            ph = encode_placeholder("S", snippet, use_b26)
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
            ph = encode_placeholder("C", snippet, use_b26)
            out.append(indent + "# " + ph)
            if had_nl:
                out.append("\n")
            pos = le

    return "".join(out)


# ========= unmask 本体（プレースホルダだけ正規表現で検出） =========

def unmask_text(s: str, strict: bool = False) -> str:
    """プレースホルダを元のJinja2構文に戻す"""
    def repl_hex(m: re.Match) -> str:
        """16進数形式のプレースホルダを復元"""
        kind, length_str, hex_str = m.groups()
        try:
            return decode_placeholder_hex(kind, length_str, hex_str)
        except Exception as e:
            if strict:
                raise
            sys.stderr.write(f"[WARN] invalid hex placeholder ignored: {m.group(0)} ({e})\n")
            return m.group(0)

    def repl_b26(m: re.Match) -> str:
        """Base26形式のプレースホルダを復元"""
        kind, b26_str = m.groups()
        try:
            return decode_placeholder_b26(kind, b26_str)
        except Exception as e:
            if strict:
                raise
            sys.stderr.write(f"[WARN] invalid b26 placeholder ignored: {m.group(0)} ({e})\n")
            return m.group(0)

    out_lines = []
    for line in s.splitlines(keepends=True):
        # 行丸ごとコメントのパターン: 先頭に「# __J2OMIT_...__」または「# __J2E_B26:...__」

        # 16進数形式をチェック
        m_full_hex = re.match(r"^(\s*)#\s*(__J2OMIT_[ESCRB]_\d+_[0-9a-fA-F]+__)\s*$", line)
        if m_full_hex:
            indent, token = m_full_hex.groups()
            m = PH_RE_HEX.fullmatch(token)
            if m:
                restored = repl_hex(m)
                out_lines.append(indent + restored + "\n")
                continue

        # Base26形式をチェック
        m_full_b26 = re.match(r"^(\s*)#\s*(__J2[ESCRB]_B26:[A-Z]+__)\s*$", line)
        if m_full_b26:
            indent, token = m_full_b26.groups()
            m = PH_RE_B26.fullmatch(token)
            if m:
                restored = repl_b26(m)
                out_lines.append(indent + restored + "\n")
                continue

        # インラインのプレースホルダも置換
        line = PH_RE_HEX.sub(repl_hex, line)
        line = PH_RE_B26.sub(repl_b26, line)
        out_lines.append(line)

    return "".join(out_lines)


# ========= ディレクトリ一括処理 =========

def process_dir(in_dir: Path, out_dir: Path, fn: Callable[[str], str]) -> None:
    """ディレクトリ内のすべてのファイルを再帰的に処理"""
    for root, _, files in os.walk(in_dir):
        rel_root = Path(root).relative_to(in_dir)
        for name in files:
            src_path = Path(root) / name
            out_path = out_dir / rel_root / name
            out_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                data = src_path.read_text(encoding="utf-8")
                out_path.write_text(fn(data), encoding="utf-8")
            except Exception as exc:
                raise RuntimeError(f"{src_path}: {exc}") from exc


# ========= CLI =========

def usage() -> None:
    print(
        "jinja2_mask.py - Jinja2 構文マスキングツール\n\n"
        "Usage:\n"
        "  jinja2_mask.py mask   [--in FILE | --in-dir DIR] [--out FILE | --out-dir DIR] [OPTIONS]\n"
        "  jinja2_mask.py unmask [--in FILE | --in-dir DIR] [--out FILE | --out-dir DIR] [--strict]\n\n"
        "Options for mask:\n"
        "  --use-b26                    Base26エンコーディングを使用 (デフォルト: 16進数)\n"
        "  --allow-inline-statements    {% %} の行内配置を許可 (デフォルト: 許可)\n"
        "  --no-allow-inline-statements {% %} の行内配置を禁止\n"
        "  --protect-backslash          バックスラッシュ文字列を保護 (デフォルト: 有効)\n"
        "  --no-protect-backslash       バックスラッシュ文字列保護を無効化\n\n"
        "Options for unmask:\n"
        "  --strict                     プレースホルダのデコードエラーで停止\n\n"
        "Examples:\n"
        "  jinja2_mask.py mask --in template.j2 --out masked.py\n"
        "  jinja2_mask.py mask --use-b26 < template.j2 > masked.py\n"
        "  jinja2_mask.py mask --in-dir templates/ --out-dir masked/ --use-b26\n"
        "  jinja2_mask.py unmask --in masked.py --out template.j2\n",
        file=sys.stderr,
    )
    sys.exit(2)


def parse_args() -> tuple[str, dict[str, object]]:
    """コマンドライン引数をパース"""
    if len(sys.argv) < 2:
        usage()
    cmd = sys.argv[1]
    if cmd not in ("mask", "unmask"):
        usage()

    opts: dict[str, object] = {}
    it = iter(sys.argv[2:])
    for arg in it:
        if arg in ("--use-b26", "--strict", "--allow-inline-statements",
                   "--no-allow-inline-statements", "--protect-backslash",
                   "--no-protect-backslash"):
            opts[arg] = True
        elif arg.startswith("--"):
            try:
                opts[arg] = next(it)
            except StopIteration:
                usage()
        else:
            # 位置引数 (互換性のため)
            opts["--in"] = arg

    return cmd, opts


def main():
    cmd, opts = parse_args()

    # オプション取得
    in_file = opts.get("--in")
    out_file = opts.get("--out")
    in_dir = opts.get("--in-dir")
    out_dir = opts.get("--out-dir")

    # mask オプション
    use_b26 = bool(opts.get("--use-b26"))
    allow_inline = not bool(opts.get("--no-allow-inline-statements"))
    protect_backslash = not bool(opts.get("--no-protect-backslash"))

    # unmask オプション
    strict = bool(opts.get("--strict"))

    # 処理関数の準備
    if cmd == "mask":
        fn = lambda text: mask_text(text, use_b26=use_b26, allow_inline=allow_inline, protect_backslash=protect_backslash)
    elif cmd == "unmask":
        fn = lambda text: unmask_text(text, strict=strict)
    else:
        usage()
        return

    try:
        # ディレクトリ処理
        if in_dir:
            if not out_dir:
                raise RuntimeError("--in-dir を使う場合は --out-dir も指定してください")
            process_dir(Path(in_dir), Path(out_dir), fn)
            return

        # ファイル処理
        if in_file:
            src = Path(in_file).read_text(encoding="utf-8")
        else:
            src = sys.stdin.read()

        result = fn(src)

        if out_file:
            path = Path(out_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(result, encoding="utf-8")
        else:
            sys.stdout.write(result)

    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
