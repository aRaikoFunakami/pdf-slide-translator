# PDF翻訳キャッシュ管理モジュール
import json
import hashlib
from pathlib import Path
from typing import Dict, Any, Tuple
from translation import extract_spans, translate_spans_openai_async

CACHE_DIR = Path("translation_cache")
CACHE_DIR.mkdir(exist_ok=True)
BATCH_SIZE = 50


def get_file_hash(file_path: str) -> str:
    """
    ファイル内容のSHA256ハッシュを返す（キャッシュキー用）
    """
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()


def build_or_load_cache(
    base_pdf: str, target_lang: str = "en"
) -> Tuple[Path, Dict[str, Any]]:
    """
    PDFのテキスト抽出+翻訳結果をキャッシュ化。キャッシュがあれば読込。
    戻り値: (キャッシュファイルPath, span属性+翻訳文のdict)
    """
    file_hash = get_file_hash(base_pdf)
    cache_file = CACHE_DIR / f"{file_hash}.json"
    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            return cache_file, json.load(f)
    spans = extract_spans(base_pdf)
    translated_map: Dict[str, str] = {}
    batches = [spans[i : i + BATCH_SIZE] for i in range(0, len(spans), BATCH_SIZE)]
    results = {}
    import asyncio
    for batch in batches:
        batch_result = asyncio.run(translate_spans_openai_async(batch, target_lang=target_lang))
        for i, it in enumerate(batch):
            results[it["id"]] = batch_result[i]
    translated_map = results
    print(f"[DEBUG] build_or_load_cache: translated_map size = {len(translated_map)}")
    if len(translated_map) == 0:
        print(
            "[WARNING] 翻訳APIから結果が得られませんでした。APIキー・ネットワーク・レートリミット等を確認してください。"
        )
    cache: Dict[str, Any] = {}
    for it in spans:
        cache_entry = dict(it)
        cache_entry["translated"] = translated_map.get(it["id"], it["text"])
        cache[it["id"]] = cache_entry
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    print(f"✅ Cache built and saved: {cache_file}")
    return cache_file, cache
