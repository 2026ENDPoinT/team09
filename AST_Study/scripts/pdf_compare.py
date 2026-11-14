"""Run the same full-document vision and summary workflow for two text extractors.

The variants use separate local documents, paid-response caches, and ledgers. The
single user-approved budget is shared in sequence; the source document is untouched.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import shutil
import time
from types import SimpleNamespace

from pdf_equation_font import HYHWPEQ_GLYPHS
from pdf_pipeline import emit, make_chunks, write_json, check_cancel, repaired_textmap

COMPARISON_VERSION = "extractor-comparison-v1"
MODES = (("markitdown", "MarkItDown"), ("direct", "pdfplumber 직접 추출"))


def variant_folder(folder: Path, document: dict, mode: str) -> Path:
    version = (importlib.metadata.version("markitdown") if mode == "markitdown"
               else importlib.metadata.version("pdfplumber"))
    key = hashlib.sha256(json.dumps([COMPARISON_VERSION, document["documentId"],
        document["fingerprint"], mode, version], ensure_ascii=False).encode()).hexdigest()[:24]
    return folder / "comparison" / f"{mode}-{key}"


def _source_copy(folder: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    source = folder / "source.pdf"
    destination = target / "source.pdf"
    if destination.exists():
        return
    try:
        os.link(source, destination)
    except OSError:
        shutil.copyfile(source, destination)


def prepare_variant(folder: Path, document: dict, mode: str) -> tuple[Path, dict, float, bool, list[int]]:
    """Do actual local extraction after approval, with stable caches for safe resume."""
    if mode not in dict(MODES):
        raise ValueError("알 수 없는 PDF 비교 방식")
    target = variant_folder(folder, document, mode)
    _source_copy(folder, target)
    cache = target / "document.json"
    if cache.is_file():
        saved = json.loads(cache.read_text(encoding="utf-8"))
        if (saved.get("documentId") == document["documentId"] and
                saved.get("comparisonVersion") == COMPARISON_VERSION and
                saved.get("comparisonMode") == mode):
            return target, saved, 0.0, True, saved.get("extractionFallbackPages", [])

    started = time.monotonic()
    candidate = copy.deepcopy(document)
    candidate["comparisonVersion"] = COMPARISON_VERSION
    candidate["comparisonMode"] = mode
    candidate["fingerprint"] = document["fingerprint"] + ";" + COMPARISON_VERSION + ";" + mode
    fallback_pages = []
    if mode == "markitdown":
        # A one-page PDF is supplied to the same local converter used before this
        # comparison feature. No LLM client, plugin, or cloud converter is loaded.
        import dotenv
        dotenv.find_dotenv = lambda *args, **kwargs: ""
        dotenv.load_dotenv = lambda *args, **kwargs: False
        from markitdown import MarkItDown
        from pypdf import PdfReader, PdfWriter
        reader = PdfReader(folder / "source.pdf")
        converter = MarkItDown(enable_plugins=False)
        for index, page in enumerate(candidate["pages"]):
            check_cancel(folder)
            emit("progress", page=index + 1, total=len(candidate["pages"]), stage="비교 1/2 · MarkItDown 변환")
            one = PdfWriter()
            one.add_page(reader.pages[index])
            stream = io.BytesIO()
            one.write(stream)
            stream.seek(0)
            try:
                page["markdown"] = converter.convert_stream(stream, file_extension=".pdf").text_content or ""
                repair = page.get("fontRepair") or {}
                if repair.get("replacedGlyphs") and not repair.get("otherPrivateUseGlyphs"):
                    page["markdown"] = page["markdown"].translate(HYHWPEQ_GLYPHS)
            except Exception:
                page["markdown"] = page.get("nativeText", "")
                fallback_pages.append(index + 1)
    else:
        import pdfplumber
        with pdfplumber.open(folder / "source.pdf") as pdf:
            for index, page in enumerate(candidate["pages"]):
                check_cancel(folder)
                emit("progress", page=index + 1, total=len(candidate["pages"]), stage="비교 2/2 · pdfplumber 직접 추출")
                try:
                    textmap, _, repair = repaired_textmap(pdf.pages[index])
                    page["nativeText"] = ((textmap.as_string if textmap is not None
                                           else pdf.pages[index].extract_text()) or "")
                    if repair["replacedGlyphs"] or repair["unresolvedGlyphs"]:
                        page["fontRepair"] = repair
                except Exception:
                    page["nativeText"] = ""
                    fallback_pages.append(index + 1)
                page["markdown"] = page["nativeText"]

    for page in candidate["pages"]:
        page.pop("pageAnalysis", None)
        page["slideLensRegions"] = [region for region in page.get("slideLensRegions", [])
                                    if region.get("origin") != "page-vision-v1"]
    candidate["chunks"] = make_chunks(document["documentId"], candidate["pages"],
                                      "markdown" if mode == "markitdown" else "nativeText")
    candidate["pageAnalysisStates"] = [{"page": page["number"], "state": "pending", "analyzed": 0, "complete": 0}
                                       for page in candidate["pages"]]
    candidate["pageAnalysisIncompletePages"] = [page["number"] for page in candidate["pages"]]
    candidate["extractionFallbackPages"] = fallback_pages
    elapsed = time.monotonic() - started
    candidate["extractionSeconds"] = round(elapsed, 3)
    write_json(cache, candidate)
    return target, candidate, elapsed, False, fallback_pages


def cumulative_usage(target: Path) -> dict:
    """Count all paid attempts for this extractor, including earlier resumptions."""
    from pdf_ai import run_usage

    requests = []
    for path in (target / "usage").glob("*.json"):
        try:
            ledger = json.loads(path.read_text(encoding="utf-8"))
            requests.extend(ledger.get("requests", []))
        except (OSError, ValueError, TypeError):
            continue
    return run_usage(SimpleNamespace(ledger={"requests": requests}))


def compare(folder: Path, document: dict, max_usd: float, model: str, transport=None,
            retry_missing_responses=False, credit_wallet=None) -> dict:
    """Finish MarkItDown before starting direct extraction, vision, or summarization."""
    from pdf_ai import Provider, generation, run_usage, BudgetExceeded

    if model != "gpt-6-luna" or not 0 < max_usd <= 10:
        raise ValueError("전체 페이지 비교에는 GPT-6 Luna와 $0 초과 $10 이하의 합산 예산이 필요합니다.")
    started = time.monotonic()
    output = {"kind": "extraction_comparison", "version": COMPARISON_VERSION,
              "documentId": document["documentId"], "model": model, "budgetUsd": max_usd,
              "variants": []}
    remaining = max_usd
    report = folder / "comparison" / "latest-report.json"
    for mode, label in MODES:
        check_cancel(folder)
        if remaining <= 0:
            output["variants"].append({"mode": mode, "label": label, "status": "skipped_due_to_budget",
                                       "cumulativeUsage": cumulative_usage(variant_folder(folder, document, mode))})
            continue
        emit("progress", page=0, total=len(document["pages"]), stage=f"{label} · 전체 분석·요약 시작")
        stage_started = time.monotonic()
        variant = {"mode": mode, "label": label}
        provider = None
        target = None
        try:
            target, variant_document, preparation, extraction_cached, fallback = prepare_variant(folder, document, mode)
            variant.update(extractionSeconds=round(preparation, 3), extractionCached=extraction_cached,
                           extractionFallbackPages=fallback)
            provider = Provider(target, True, remaining, model, transport=transport,
                                retry_missing_responses=retry_missing_responses, max_allowed_usd=10)
            if credit_wallet is not None:
                from pdf_credit_billing import Billing
                provider.billing=Billing(credit_wallet,provider.ledger['operationId'],'analysis',ledger_path=provider.ledger_path)
                provider.ledger['category']='analysis'
            generation_started = time.monotonic()
            result = generation(target, variant_document, provider, "document", 0, page_mode=True)
            variant.update(status="complete", generationSeconds=round(time.monotonic() - generation_started, 3),
                           result=result)
        except InterruptedError:
            raise
        except Exception as failure:
            # Transport exceptions can contain response bodies or source excerpts.
            # Only known local errors may be shown in the saved report.
            safe = isinstance(failure, BudgetExceeded)
            variant.update(status="budget_exhausted" if isinstance(failure, BudgetExceeded) else "failed",
                           error=(str(failure)[:300] if safe else
                                  f"{type(failure).__name__}: 분석 중 오류가 발생했습니다. 완료 캐시는 보존됩니다."))
        if provider is not None:
            variant["usage"] = run_usage(provider)
            remaining = max(0.0, remaining - provider.spent)
        if target is not None:
            variant["cumulativeUsage"] = cumulative_usage(target)
        variant["seconds"] = round(time.monotonic() - stage_started, 3)
        output["variants"].append(variant)
        output["totalSeconds"] = round(time.monotonic() - started, 3)
        output["usageBasedUsd"] = round(sum(v.get("usage", {}).get("usageBasedUsd", 0)
                                            for v in output["variants"]), 8)
        output["uncertainReservedUsd"] = round(sum(v.get("usage", {}).get("uncertainReservedUsd", 0)
                                                for v in output["variants"]), 8)
        output["cumulativeUsageBasedUsd"] = round(sum(v.get("cumulativeUsage", {}).get("usageBasedUsd", 0)
                                                       for v in output["variants"]), 8)
        output["cumulativeUncertainReservedUsd"] = round(sum(v.get("cumulativeUsage", {}).get("uncertainReservedUsd", 0)
                                                              for v in output["variants"]), 8)
        write_json(report, output)
        if variant["status"] == "budget_exhausted":
            break
    for mode, label in MODES[len(output["variants"]):]:
        target = variant_folder(folder, document, mode)
        output["variants"].append({"mode": mode, "label": label, "status": "skipped_due_to_budget",
                                   "cumulativeUsage": cumulative_usage(target)})
    output["totalSeconds"] = round(time.monotonic() - started, 3)
    output["cumulativeUsageBasedUsd"] = round(sum(v.get("cumulativeUsage", {}).get("usageBasedUsd", 0)
                                                 for v in output["variants"]), 8)
    output["cumulativeUncertainReservedUsd"] = round(sum(v.get("cumulativeUsage", {}).get("uncertainReservedUsd", 0)
                                                      for v in output["variants"]), 8)
    write_json(report, output)
    return output
