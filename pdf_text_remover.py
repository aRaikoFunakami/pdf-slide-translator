# PDF物理テキスト削除モジュール
import fitz  # PyMuPDF
import pikepdf

def remove_page_text_keep_images_graphics(src: str, dst: str) -> None:
    """
    ページ上のテキストのみを物理削除し、画像・線画は保持する（PyMuPDF使用）
    """
    doc = fitz.open(src)
    for page in doc:
        page.add_redact_annot(page.rect)
        page.apply_redactions(
            images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE
        )
    doc.save(dst, deflate=True, clean=True)
    doc.close()

TEXT_OPS = {b"Tj", b"TJ", b"'", b'"'}

def _strip_text_ops_from_stream(obj: pikepdf.Stream) -> None:
    """
    PDFストリームからテキスト描画命令(Tj/TJ等)を除去
    """
    try:
        instrs = pikepdf.parse_content_stream(obj, operators="*")
    except Exception:
        return
    cleaned = []
    for operands, operator in instrs:
        if operator in TEXT_OPS:
            continue
        cleaned.append((operands, operator))
    try:
        new_bytes = pikepdf.unparse_content_stream(cleaned)
        obj._set_stream(new_bytes)
    except Exception:
        pass


def _scrub_xobject_recursive(
    pdf: pikepdf.Pdf, resources: pikepdf.Dictionary, seen: set[int]
) -> None:
    """
    XObject/Form/Pattern等のネストしたストリームからもテキスト命令を除去（再帰）
    """
    if not isinstance(resources, pikepdf.Dictionary):
        return
    xobjs = resources.get("/XObject", None)
    if isinstance(xobjs, pikepdf.Dictionary):
        for _, ref in list(xobjs.items()):
            try:
                xo = ref.get_object()
            except Exception:
                continue
            if isinstance(xo, pikepdf.Stream):
                xref = int(xo.objgen[0])
                if xref in seen:
                    continue
                seen.add(xref)
                _strip_text_ops_from_stream(xo)
                if xo.get("/Subtype", None) == "/Form":
                    _scrub_xobject_recursive(
                        pdf, xo.get("/Resources", pikepdf.Dictionary()), seen
                    )
    pats = resources.get("/Pattern", None)
    if isinstance(pats, pikepdf.Dictionary):
        for _, ref in list(pats.items()):
            try:
                pat = ref.get_object()
            except Exception:
                continue
            if isinstance(pat, pikepdf.Stream):
                _strip_text_ops_from_stream(pat)


def _scrub_appearances(annot_obj: pikepdf.Dictionary) -> None:
    """
    アノテーションの外観ストリームからテキスト命令を除去
    """
    ap = annot_obj.get("/AP", None)
    if isinstance(ap, pikepdf.Dictionary):
        for key in ("/N", "/R", "/D"):
            stream = ap.get(key, None)
            if hasattr(stream, "get_object"):
                try:
                    sobj = stream.get_object()
                except Exception:
                    continue
                if isinstance(sobj, pikepdf.Stream):
                    _strip_text_ops_from_stream(sobj)


def _scrub_metadata_trees(pdf: pikepdf.Pdf) -> None:
    """
    Outlines/StructTreeRoot等のメタデータツリーから文字列を除去
    """
    for key in ["/Outlines", "/StructTreeRoot"]:
        node = pdf.Root.get(key, None)
        if isinstance(node, pikepdf.Dictionary):
            for k in list(node.keys()):
                if isinstance(node[k], (str, pikepdf.String)):
                    node[k] = ""


def scrub_non_page_text(src: str, dst: str) -> None:
    """
    ページ外のテキスト（AcroForm/Annots/XObject/メタデータ等）を徹底的に除去
    """
    pdf = pikepdf.open(src)
    acro = pdf.Root.get("/AcroForm", None)
    if isinstance(acro, pikepdf.Dictionary):
        fields = acro.get("/Fields", None)
        if isinstance(fields, pikepdf.Array):
            for fref in fields:
                try:
                    fobj = fref.get_object()
                except Exception:
                    continue
                for k in ("/V", "/T", "/TU", "/DA"):
                    if k in fobj:
                        fobj[k] = ""
    for page in pdf.pages:
        annots = page.get("/Annots", None)
        if isinstance(annots, pikepdf.Array):
            for aref in annots:
                try:
                    aobj = aref.get_object()
                except Exception:
                    continue
                for k in ("/Contents", "/T", "/TU", "/DA"):
                    if k in aobj:
                        aobj[k] = ""
                _scrub_appearances(aobj)
        _scrub_xobject_recursive(
            pdf, page.get("/Resources", pikepdf.Dictionary()), set()
        )
    _scrub_metadata_trees(pdf)
    pdf.save(dst, compress_streams=True)
    pdf.close()


# --- CLIエントリポイント ---
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="PDFテキスト物理削除（画像・線画保持）"
    )
    parser.add_argument("input", help="入力PDFファイル名")
    parser.add_argument(
        "-o", "--output", help="出力PDFファイル名（省略時は _text_removed.pdf を付加）"
    )
    args = parser.parse_args()
    input_pdf = args.input
    import os

    step1_pdf = os.path.join(
        os.path.dirname(input_pdf), f"_step1_{os.path.basename(input_pdf)}"
    )
    if args.output:
        output_pdf = args.output
    else:
        basename = os.path.basename(input_pdf)
        dirname = os.path.dirname(input_pdf)
        output_pdf = os.path.join(
            dirname, f"{os.path.splitext(basename)[0]}_text_removed.pdf"
        )
    remove_page_text_keep_images_graphics(input_pdf, step1_pdf)
    scrub_non_page_text(step1_pdf, output_pdf)
    try:
        os.remove(step1_pdf)
    except Exception:
        pass
    print(f"✅ テキスト物理削除PDFを出力: {output_pdf}")
