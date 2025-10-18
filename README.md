# PDF翻訳・オーバーレイツール

## 概要

PDFファイルからテキストを抽出し、OpenAI APIを利用して翻訳し、翻訳文を元のレイアウトに重ねて新しいPDFを生成するツールです。日本語・英語の相互翻訳に対応しています。

## 機能

- PDFテキストの抽出
- テキストスパンごとの属性情報取得（位置・色・フォント等）
- OpenAI APIによる高精度な翻訳（非同期・進捗バー表示）
- 翻訳結果のキャッシュ保存・再利用
- 元PDFレイアウトに翻訳文をオーバーレイ
- CLIによる一括処理

## インストール

Python 3.13 以上が必要です。
依存パッケージは `uv` を使ってインストールしてください。

```sh
uv sync
```

## 使用方法

### コマンドライン例

```sh
uv run python main.py ./samples/input.pdf
```

### コード例

```python
from translation import extract_spans, translate_spans_openai_async
spans = extract_spans('input.pdf')
translations = await translate_spans_openai_async(spans, target_lang='en')
```

## オプション

- 入力PDFパス
- 出力PDFパス
- キャッシュディレクトリ指定
- 翻訳対象言語（en/ja）
- OpenAIモデル指定（環境変数 OPENAI_MODEL）

## 仕様

- テキスト抽出はPyMuPDF（fitz）を使用
- 各テキストスパンの属性（bbox, font, color等）を保持
- 翻訳結果はJSONキャッシュとして保存
- キャッシュが存在する場合はAPI呼び出しを省略
- 進捗バー表示（tqdm）
- オーバーレイはFreeTextアノテーションで実装

## 制限事項 / 既知の問題

- 縦書きPDFは非対応
- 画像化されたテキストは抽出不可
- 一部フォント・色情報が正確に再現されない場合あり
- OpenAI APIのレスポンス仕様変更に依存

## 作者

- raiko.funakami
- [GitHub](https://github.com/raiko-funakami)
- 縦書きPDFは非対応
- 画像化されたテキストは抽出不可
- 一部フォント・色情報が正確に再現されない場合あり
- OpenAI APIのレスポンス仕様変更に依存

## 作者
- raiko.funakami
- GitHub: https://github.com/raiko-funakami
