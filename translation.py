# PDFテキスト抽出・翻訳・オーバーレイ用モジュール
import os
import json
import fitz
import asyncio
import sys
from typing import List, Dict, Any, Tuple
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from tqdm.asyncio import tqdm

# LibreTranslate対応
try:
    from libretranslatepy import LibreTranslateAPI
    LIBRETRANSLATE_AVAILABLE = True
except ImportError:
    LIBRETRANSLATE_AVAILABLE = False
    LibreTranslateAPI = None

# OPENAI_API_KEYの存在チェック
if not os.getenv("OPENAI_API_KEY"):
    print("エラー: OPENAI_API_KEYが設定されていません。")
    print("環境変数OPENAI_API_KEYを設定してから実行してください。")
    sys.exit(1)

# openai api を利用する場合の設定
# モデル設定は動的に取得するため、ここでは設定しない

# local LLMサーバー利用時の例
# OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-oss:20b")
# OPENAI_BASEURL = os.getenv("OPENAI_BASEURL", "http://localhost:11434/v1")


def get_model_config():
    """
    現在の環境変数からモデル設定を取得する
    """
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    
    # LibreTranslateの場合
    if model.lower() == "libre":
        baseurl = os.getenv("OPENAI_BASEURL", "http://127.0.0.1:5001/")
        print(f"Using LibreTranslate: {baseurl}")
        return model, baseurl
    
    # LTEngineの場合
    if model.lower() == "ltengine":
        baseurl = os.getenv("OPENAI_BASEURL", "http://127.0.0.1:5050/")
        print(f"Using LTEngine: {baseurl}")
        return model, baseurl
    
    # OSSモデルかどうかを判定してBASEURLを設定
    if "oss" in model.lower() or "local" in model.lower():
        baseurl = os.getenv("OPENAI_BASEURL", "http://localhost:11434/v1")
    else:
        baseurl = os.getenv("OPENAI_BASEURL", "")
    
    print(f"Using OPENAI_MODEL: {model}")
    if baseurl:
        print(f"Using OPENAI_BASEURL: {baseurl}")
    
    return model, baseurl


def extract_spans(pdf_path: str) -> List[Dict[str, Any]]:
    """
    PDFからテキストspan情報を抽出する。
    各spanのid, text, color, size, bbox, font, その他属性を辞書で返す。
    """
    doc = fitz.open(pdf_path)
    items: List[Dict[str, Any]] = []
    for p_i, page in enumerate(doc):
        blocks = page.get_text("dict").get("blocks", [])
        for b_i, b in enumerate(blocks):
            for l_i, line in enumerate(b.get("lines", [])):
                for s_i, span in enumerate(line.get("spans", [])):
                    text = (span.get("text") or "").strip()
                    if not text:
                        continue
                    item_id = f"p{p_i}_b{b_i}_l{l_i}_s{s_i}"
                    span_data = dict(span)
                    span_data["id"] = item_id
                    span_data["color"] = normalize_color(span.get("color", (0, 0, 0)))
                    items.append(span_data)
    doc.close()
    return items


def normalize_color(span_color: Any) -> Tuple[float, float, float]:
    """
    spanのcolor属性をRGB(0..1)タプルに正規化
    """
    if isinstance(span_color, int):
        r = (span_color >> 16) & 255
        g = (span_color >> 8) & 255
        b = span_color & 255
        return (r / 255.0, g / 255.0, b / 255.0)
    if isinstance(span_color, (list, tuple)) and len(span_color) >= 3:
        r, g, b = span_color[0], span_color[1], span_color[2]
        if max(r, g, b) > 1.0:
            return (float(r) / 255.0, float(g) / 255.0, float(b) / 255.0)
        return (float(r), float(g), float(b))
    return (0.0, 0.0, 0.0)


def overlay_translations(
    transparent_pdf: str, cache: Dict[str, Any], output_pdf: str
) -> None:
    """
    テキスト消去済みPDFに、翻訳文を元のspan属性に基づきFreeTextアノテーションとして重ねる。
    - bbox, font, size, color, opacity, rotationを反映
    - rect幅は翻訳文の長さに応じて自動拡張
    """
    doc = fitz.open(transparent_pdf)
    for p_i, page in enumerate(doc):
        for span_id, entry in cache.items():
            if not span_id.startswith(f"p{p_i}_"):
                continue
            txt = entry.get("translated")
            if not txt:
                continue
            bbox = entry.get("bbox")
            fontsize = entry.get("size", 12)
            font = entry.get("font", "helv")
            color = entry.get("color", (0, 0, 0))
            opacity = entry.get("opacity", 1.0)
            rotation = entry.get("rotation", 0)
            if bbox:
                rect = fitz.Rect(bbox)
                # テキスト幅を計算（日本語は幅広めに）
                try:
                    text_width = page.get_text_length(
                        txt, fontsize=fontsize, fontname=font
                    )
                except Exception:
                    if any(ord(c) >= 0x3000 for c in txt):
                        fallback_coeff = 1.0
                    else:
                        fallback_coeff = 0.6
                    text_width = len(txt) * fontsize * fallback_coeff
                new_rect = fitz.Rect(
                    rect.x0, rect.y0, rect.x0 + text_width + 2, rect.y1
                )
                # FreeTextアノテーション追加
                annot = page.add_freetext_annot(
                    new_rect,
                    txt,
                    fontsize=fontsize,
                    fontname=font,
                    text_color=tuple(color),
                    fill_color=None,
                    align=0,
                )
                # 透明度・回転のみ反映（API制約）
                try:
                    if opacity is not None:
                        annot.set_opacity(opacity)
                    if rotation:
                        annot.set_rotation(rotation)
                except Exception:
                    pass
                annot.update()
    doc.save(output_pdf)
    doc.close()


async def translate_spans_openai_async(spans, target_lang="en"):
    """
    OpenAI APIでPDFテキストspanリストを一括翻訳する（非同期版）。
    spans: span辞書リスト
    target_lang: 'en' or 'ja'
    戻り値: 翻訳文リスト（元spansと同じ順）

    並列実行の仕組み:
    - spansをbatch_size（例:25件）ずつ分割し、各チャンクを非同期で処理します。
    - 各チャンクの翻訳処理はprocess_chunk()で行い、LangChainのAPI呼び出し部分はloop.run_in_executor()でスレッドプール上で実行されます。
    - asyncio.gather()により、複数のチャンクが同時にスレッドで並列実行されます。
    - PythonのThreadPoolExecutorの最大スレッド数（デフォルト: min(32, os.cpu_count() + 4)）まで同時実行され、それ以上は順次処理されます。
    """
    
    # モデル設定を取得してLibreTranslateかどうかを判定
    openai_model, openai_baseurl = get_model_config()
    
    # LibreTranslateまたはLTEngineの場合は専用関数を呼び出し
    if openai_model.lower() in ["libre", "ltengine"]:
        return await translate_spans_libretranslate_async(spans, target_lang, openai_baseurl)

    if not spans:
        return [""] * len(spans)

    class TranslationItem(BaseModel):
        id: str = Field(description="span id")
        translated: str = Field(description="translated text")

    class TranslationResult(BaseModel):
        translations: list[TranslationItem] = Field(
            description="list of translated items"
        )

    parser = JsonOutputParser(pydantic_object=TranslationResult)

    # モデル設定を動的に取得
    openai_model, openai_baseurl = get_model_config()

    if openai_baseurl:
        model = ChatOpenAI(temperature=0, model=openai_model, openai_api_base=openai_baseurl)
    else:
        model = ChatOpenAI(temperature=0, model=openai_model)

    batch_size = 10
    all_translations = []

    async def process_chunk(chunk, pbar=None):
        items_json = json.dumps(
            [{"id": it["id"], "text": it["text"]} for it in chunk], ensure_ascii=False
        )
        prompt = PromptTemplate(
            template=(
                "You are a professional translator. Please translate each text in the following list to "
                + ("English" if target_lang == "en" else "Japanese")
                + ". Return the result as a strict JSON object.\n"
                "The output format must be:\n"
                '{{\n  "translations": [\n    {{"id": "p0_b0_l0_s0", "translated": "Translated text 1"}},\n    {{"id": "p0_b0_l0_s1", "translated": "Translated text 2"}},\n    ...\n  ]\n}}\n'
                "Do not include any explanations or extra text. Only output the JSON object in the specified format.\n"
                "Here is the list of items to translate (as JSON):\n{items_json}\n"
                "{format_instructions}"
            ),
            input_variables=["items_json"],
            partial_variables={"format_instructions": parser.get_format_instructions()},
        )
        chain = prompt | model | parser
        try:
            # LangChainの非同期APIを直接await
            result = await chain.ainvoke({"items_json": items_json})
            if not (isinstance(result, dict) and "translations" in result):
                print(
                    f"[ERROR] LangChain APIレスポンスにtranslationsが見つかりません: {str(result)[:100]}"
                )
                return [""] * len(chunk)
            translations = result["translations"]
            id_to_trans = {item["id"]: item["translated"] for item in translations}
            chunk_translations = [id_to_trans.get(it["id"], "") for it in chunk]
            
            # 進捗バーを更新
            if pbar:
                pbar.update(len(chunk))
                
            return chunk_translations
        except Exception as e:
            print(f"[ERROR] LangChain APIレスポンスのパースに失敗: {e}")
            if pbar:
                pbar.update(len(chunk))
            return [""] * len(chunk)

    # 進捗バーを初期化
    total_spans = len(spans)
    with tqdm(total=total_spans, desc="翻訳中", unit="spans") as pbar:
        tasks = [
            process_chunk(spans[i : i + batch_size], pbar)
            for i in range(0, len(spans), batch_size)
        ]
        results = await asyncio.gather(*tasks)
        
    for chunk_result in results:
        all_translations.extend(chunk_result)
    return all_translations


async def translate_spans_libretranslate_async(spans, target_lang="en", baseurl="http://127.0.0.1:5001/"):
    """
    LibreTranslate/LTEngine APIでPDFテキストspanリストを翻訳する（非同期版）。
    spans: span辞書リスト
    target_lang: 'en' or 'ja'
    baseurl: LibreTranslate/LTEngineサーバーのURL
    戻り値: 翻訳文リスト（元spansと同じ順）
    """
    if not LIBRETRANSLATE_AVAILABLE:
        print("エラー: libretranslatepyがインストールされていません。")
        print("pip install libretranslate-py でインストールしてください。")
        return [""] * len(spans)
    
    if not spans:
        return [""] * len(spans)

    try:
        lt = LibreTranslateAPI(baseurl)
        
        # 言語検出とマッピング
        source_lang = "ja" if target_lang == "en" else "en"
        
        all_translations = []
        
        # 進捗バーを使って翻訳
        engine_name = "LTEngine" if "5050" in baseurl else "LibreTranslate"
        with tqdm(total=len(spans), desc=f"翻訳中 ({engine_name})", unit="spans") as pbar:
            for span in spans:
                text = span.get("text", "").strip()
                if not text:
                    all_translations.append("")
                    pbar.update(1)
                    continue
                
                try:
                    # LibreTranslate/LTEngineで翻訳実行
                    translated = lt.translate(text, source_lang, target_lang)
                    #print(f"[DEBUG] {engine_name}翻訳: {text} -> {translated}")
                    all_translations.append(translated)
                except Exception as e:
                    print(f"[ERROR] {engine_name}翻訳エラー: {e}")
                    all_translations.append(text)  # 元のテキストをそのまま使用
                
                pbar.update(1)
        
        return all_translations
        
    except Exception as e:
        engine_name = "LTEngine" if "5050" in baseurl else "LibreTranslate"
        print(f"[ERROR] {engine_name}接続エラー: {e}")
        print(f"{engine_name}サーバー ({baseurl}) が起動していることを確認してください。")
        return [""] * len(spans)
