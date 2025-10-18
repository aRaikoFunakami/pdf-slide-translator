# PDF翻訳オーバーレイCLI
import os
import argparse
import tempfile
from cache import build_or_load_cache
from pdf_text_remover import remove_page_text_keep_images_graphics, scrub_non_page_text
from translation import overlay_translations


def parse_args():
    """
    コマンドライン引数のパース
    """
    parser = argparse.ArgumentParser(description="PDF翻訳オーバーレイ")
    parser.add_argument("input", help="入力PDFファイル名")
    parser.add_argument(
        "-o", "--output", help="出力PDFファイル名（省略時は translated_ を付加）"
    )
    parser.add_argument("-e", action="store_true", help="日本語→英語に翻訳")
    parser.add_argument("-j", action="store_true", help="英語→日本語に翻訳")
    parser.add_argument(
        "-c", action="store_true", help="キャッシュを利用する（テスト用）"
    )
    parser.add_argument(
        "-m", "--model", help="AIモデル名（例: gpt-4.1-mini, gpt-oss:20b）"
    )
    parser.add_argument(
        "-u", "--baseurl", help="OPENAI_BASEURL（OSSモデル使用時）"
    )
    return parser.parse_args()


def main():
    """
    PDF翻訳オーバーレイ処理本体
    1. テキスト抽出・翻訳（キャッシュ利用可）
    2. 元PDFからテキスト物理削除
    3. 翻訳文をFreeTextアノテーションで重ねて出力
    """
    args = parse_args()
    
    # AIモデルとBASEURLの設定
    if args.model:
        os.environ["OPENAI_MODEL"] = args.model
    
    if args.baseurl:
        os.environ["OPENAI_BASEURL"] = args.baseurl
    elif args.model and ("oss" in args.model.lower() or "local" in args.model.lower()):
        # OSSモデルでBASEURLが指定されていない場合のデフォルト値
        if not os.getenv("OPENAI_BASEURL"):
            os.environ["OPENAI_BASEURL"] = "http://localhost:11434/v1"
    
    BASE_PDF = args.input
    # 出力ファイル名決定
    if args.output:
        OUTPUT_PDF = args.output
    else:
        basename = os.path.basename(BASE_PDF)
        dirname = os.path.dirname(BASE_PDF)
        OUTPUT_PDF = os.path.join(dirname, f"translated_{basename}")
    tmpdir = tempfile.gettempdir()
    step1_pdf = os.path.join(tmpdir, f"tr_step1_{os.getpid()}.pdf")
    # 翻訳言語決定
    target_lang = "en" if args.e else ("ja" if args.j else "en")
    # 1. テキスト抽出・翻訳（キャッシュ利用）
    if args.c:
        cache_file, cache = build_or_load_cache(BASE_PDF, target_lang=target_lang)
    else:
        import asyncio
        from translation import extract_spans, translate_spans_openai_async

        spans = extract_spans(BASE_PDF)
        translations = asyncio.run(translate_spans_openai_async(spans, target_lang=target_lang))
        cache = {
            it["id"]: {**it, "translated": translations[i]}
            for i, it in enumerate(spans)
        }
    # 2. 元PDFからテキスト物理削除
    text_removed_pdf = os.path.join(tmpdir, f"tr_text_removed_{os.getpid()}.pdf")
    remove_page_text_keep_images_graphics(BASE_PDF, step1_pdf)
    scrub_non_page_text(step1_pdf, text_removed_pdf)
    try:
        os.remove(step1_pdf)
    except Exception as e:
        print(f"一時ファイル削除失敗: {e}")
    # 3. 翻訳文をFreeTextアノテーションで重ねて出力
    overlay_translations(text_removed_pdf, cache, OUTPUT_PDF)
    try:
        os.remove(text_removed_pdf)
    except Exception as e:
        print(f"一時ファイル削除失敗: {e}")


if __name__ == "__main__":
    main()
