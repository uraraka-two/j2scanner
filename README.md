# jinja2_mask.py

Jinja2 テンプレート構文を self-contained なプレースホルダに置き換え、後で元に戻すためのツール。

Jinja2 構文 (`{{ }}`, `{% %}`, `{# #}`, `#{}`）を一時的にマスクすることで、Jinja2 テンプレートを通常の Python ファイルとして扱えるようになります（lint、フォーマッター、静的解析ツールなど）。

## 特徴

- **手書きスキャナによる正確な構文検出**: 正規表現の `.*?` に頼らず、`str.find()` ベースのスキャナで Jinja2 構文を検出
- **複数のエンコーディング形式**: 16進数とBase26の2つのエンコーディング方式をサポート
- **完全可逆**: マスク→アンマスクで元の構文を100%復元
- **raw ブロック対応**: `{% raw %}...{% endraw %}` 内では `{{ }}` と `{# #}` を無視
- **バックスラッシュ文字列保護**: `"..."` 内のエスケープシーケンスを保護
- **ディレクトリ一括処理**: 再帰的にディレクトリ全体を処理可能
- **依存ゼロ**: Python 3 標準ライブラリのみで動作

## 対応構文

| 構文 | 種別 | 説明 | 配置 |
|------|------|------|------|
| `{{ ... }}` | `E` (Expression) | 変数展開 | インライン |
| `{% ... %}` | `S` (Statement) | 制御構文 | 行全体 |
| `{# ... #}` | `C` (Comment) | コメント | 行全体 |
| `#{ ... }` | `R` (Ruby style) | Ruby風補間 | インライン |
| `"...\..."` | `B` (Backslash) | バックスラッシュ文字列 | インライン |

## インストール

```bash
# リポジトリをクローン
git clone <repository-url>
cd j2scanner

# 実行権限を付与
chmod +x jinja2_mask.py
```

## 基本的な使い方

### 単一ファイルの処理

```bash
# mask: Jinja2構文をプレースホルダに置き換え
./jinja2_mask.py mask --in template.j2 --out masked.py

# unmask: プレースホルダを元のJinja2構文に戻す
./jinja2_mask.py unmask --in masked.py --out template.j2
```

### 標準入出力を使用

```bash
# mask
cat template.j2 | ./jinja2_mask.py mask > masked.py

# unmask
cat masked.py | ./jinja2_mask.py unmask > template.j2
```

### ディレクトリ一括処理

```bash
# ディレクトリ全体を再帰的に処理
./jinja2_mask.py mask --in-dir templates/ --out-dir masked/

# 元に戻す
./jinja2_mask.py unmask --in-dir masked/ --out-dir templates/
```

## プレースホルダ形式

### 16進数形式（デフォルト）

```
__J2OMIT_<KIND>_<LEN>_<HEX>__
```

- `KIND`: 構文の種別 (`E`, `S`, `C`, `R`, `B`)
- `LEN`: 元スニペットのUTF-8バイト長（10進数）
- `HEX`: 元スニペットのUTF-8バイト列を16進化した文字列

**例:**
```
{{ brokers | join(",") }}
↓
__J2OMIT_E_27_7b7b2062726f6b657273207c206a6f696e28222c2229207d7d__
```

### Base26形式（`--use-b26`）

```
__J2<KIND>_B26:<B26>__
```

- `KIND`: 構文の種別 (`E`, `S`, `C`, `R`, `B`)
- `B26`: 元スニペットをBase26エンコードした文字列（A-Zのみ）

**例:**
```
{{ brokers }}
↓
__J2E_B26:KBKBHHFHHBGPGNGMHNGMHH__
```

## コマンドラインオプション

### mask コマンド

```bash
jinja2_mask.py mask [OPTIONS]
```

#### 入出力オプション
- `--in FILE`: 入力ファイル（省略時は標準入力）
- `--out FILE`: 出力ファイル（省略時は標準出力）
- `--in-dir DIR`: 入力ディレクトリ（再帰処理）
- `--out-dir DIR`: 出力ディレクトリ（`--in-dir` と併用）

#### エンコーディングオプション
- `--use-b26`: Base26エンコーディングを使用（デフォルト: 16進数）

#### 動作制御オプション
- `--allow-inline-statements`: `{% %}` の行内配置を許可（デフォルト）
- `--no-allow-inline-statements`: `{% %}` の行内配置を禁止（エラーを発生）
- `--protect-backslash`: バックスラッシュ文字列を保護（デフォルト）
- `--no-protect-backslash`: バックスラッシュ文字列保護を無効化

### unmask コマンド

```bash
jinja2_mask.py unmask [OPTIONS]
```

#### 入出力オプション
- `--in FILE`: 入力ファイル（省略時は標準入力）
- `--out FILE`: 出力ファイル（省略時は標準出力）
- `--in-dir DIR`: 入力ディレクトリ（再帰処理）
- `--out-dir DIR`: 出力ディレクトリ（`--in-dir` と併用）

#### 動作制御オプション
- `--strict`: プレースホルダのデコードエラーで停止（デフォルト: 警告のみ）

## 使用例

### 例1: 基本的な mask/unmask

**入力 (template.j2):**
```jinja2
# Kafka brokers configuration
brokers = {{ brokers | join(",") }}

{% for topic in topics %}
# Topic: {{ topic.name }}
partitions_{{ loop.index }} = {{ topic.partitions }}
{% endfor %}

{# This is a comment #}
```

**mask 実行:**
```bash
./jinja2_mask.py mask --in template.j2 --out masked.py
```

**出力 (masked.py):**
```python
# Kafka brokers configuration
brokers = __J2OMIT_E_27_7b7b2062726f6b657273207c206a6f696e28222c2229207d7d__

# __J2OMIT_S_23_7b252066f7220746f70696320696e20746f7069637320257d__
# Topic: __J2OMIT_E_16_7b7b20746f7069632e6e616d65207d7d__
partitions___J2OMIT_E_18_7b7b206c6f6f702e696e646578207d7d__ = __J2OMIT_E_22_7b7b20746f7069632e706172746974696f6e73207d7d__
# __J2OMIT_S_13_7b2520656e64666f7220257d__

# __J2OMIT_C_23_7b232054686973206973206120636f6d6d656e7420237d__
```

**unmask 実行:**
```bash
./jinja2_mask.py unmask --in masked.py --out restored.j2
```

### 例2: Base26エンコーディング

```bash
# Base26形式でマスク
./jinja2_mask.py mask --use-b26 --in template.j2 --out masked_b26.py

# unmaskは自動的に形式を認識
./jinja2_mask.py unmask --in masked_b26.py --out restored.j2
```

### 例3: ディレクトリ一括処理

```bash
# テンプレートディレクトリ全体をマスク
./jinja2_mask.py mask --in-dir src/templates/ --out-dir build/masked/

# Lint や フォーマッターを実行
black build/masked/
ruff check build/masked/

# 元に戻す
./jinja2_mask.py unmask --in-dir build/masked/ --out-dir src/templates/
```

### 例4: インラインステートメント制御

```bash
# 行内の {% %} を禁止（より厳格なチェック）
./jinja2_mask.py mask --no-allow-inline-statements --in template.j2 --out masked.py
```

**エラー例:**
```jinja2
result = {% if condition %}value{% endif %}  # ← エラー: 行内に {% %} が混在
```

### 例5: パイプラインでの使用

```bash
# Jinja2テンプレートをマスク → Black でフォーマット → アンマスク
cat template.j2 | \
  ./jinja2_mask.py mask | \
  black --quiet - | \
  ./jinja2_mask.py unmask > formatted.j2
```

## ワークフロー例

### Python Linter との統合

```bash
#!/bin/bash
# lint_jinja2.sh - Jinja2テンプレートをLintするスクリプト

TEMPLATE_FILE=$1

# 一時ファイルを作成
MASKED_FILE=$(mktemp)

# マスク
./jinja2_mask.py mask --in "$TEMPLATE_FILE" --out "$MASKED_FILE"

# Ruff でチェック
ruff check "$MASKED_FILE"

# 一時ファイルを削除
rm "$MASKED_FILE"
```

使用例:
```bash
./lint_jinja2.sh config.py.j2
```

### CI/CD での利用

```yaml
# .github/workflows/lint.yml
name: Lint Jinja2 Templates

on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2

      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.10'

      - name: Install dependencies
        run: pip install black ruff

      - name: Mask Jinja2 templates
        run: |
          ./jinja2_mask.py mask --in-dir templates/ --out-dir masked/

      - name: Run Black
        run: black --check masked/

      - name: Run Ruff
        run: ruff check masked/
```

## 高度な使用例

### raw ブロックの処理

```jinja2
{% raw %}
# この中の {{ }} や {# #} はマスクされない
example = "{{ not_a_variable }}"
{% endraw %}

# ここの {{ variable }} はマスクされる
value = {{ variable }}
```

### バックスラッシュ文字列の保護

```python
# --protect-backslash (デフォルト)
pattern = "\\d+\\s*{{ variable }}"  # \\ が保護される

# --no-protect-backslash
pattern = "\\d+\\s*{{ variable }}"  # \\ がそのまま処理される
```

## トラブルシューティング

### プレースホルダのデコードエラー

**問題:**
```
[WARN] invalid placeholder ignored: __J2OMIT_E_10_INVALID__
```

**解決策:**
- `--strict` オプションを使用してエラー箇所を特定
```bash
./jinja2_mask.py unmask --strict --in masked.py
```

### 行内ステートメントのエラー

**問題:**
```
ValueError: 行内に {% ... %} が混在: result = {% if x %}1{% endif %}
```

**解決策:**
- `--allow-inline-statements` を使用（デフォルト）
- または、テンプレートを複数行に分割

## 技術詳細

### スキャナの仕組み

このツールは正規表現の `.*?` を使わず、`str.find()` ベースの手書きスキャナを使用しています。これにより以下の利点があります：

- **ネストした構文の正確な処理**: `{{ "{{" }}` のような複雑なケースも正しく処理
- **パフォーマンス**: 大きなファイルでも高速
- **raw ブロック対応**: 状態管理により `{% raw %}` を正確に追跡

### プレースホルダの設計原則

1. **Self-contained**: プレースホルダ自体に元の情報をすべて含む
2. **可逆性**: 情報の損失なく完全に復元可能
3. **安全性**: Python の識別子として有効な文字のみ使用
4. **検証可能**: 長さ情報によりデータ整合性を検証（16進数形式）

## 関連ファイル

- [jinja2_mask.py](jinja2_mask.py) - メインツール（16進数 + Base26 両対応）
- [j2mask.py](j2mask.py) - 旧バージョン（Base26のみ、ディレクトリ処理対応）
