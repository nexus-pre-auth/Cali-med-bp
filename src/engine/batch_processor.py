"""
BatchProcessor: run compliance reviews across a directory of PDFs concurrently.

Uses a ThreadPoolExecutor (CPU-bound PDF parsing) wrapped in asyncio so the
FastAPI server remains responsive during large batch jobs.

Usage (CLI):
    python main.py batch --input-dir /path/to/drawings --format html

Usage (Python):
    processor = BatchProcessor()
    results   = await processor.run(Path("/drawings"), fmt="html")
"""

from __future__ import annotations

import asyncio
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import config


class BatchJobResult:
    """Outcome for a single file in a batch run."""

    def __init__(self, file_path: Path) -> None:
        self.file_path     = file_path
        self.project_name  = file_path.stem
        self.success       = False
        self.error: Optional[str] = None
        self.violation_count: int = 0
        self.critical_count: int  = 0
        self.output_paths: Dict[str, str] = {}
        self.duration_seconds: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "file":             str(self.file_path),
            "project_name":     self.project_name,
            "success":          self.success,
            "error":            self.error,
            "violation_count":  self.violation_count,
            "critical_count":   self.critical_count,
            "output_paths":     self.output_paths,
            "duration_seconds": round(self.duration_seconds, 2),
        }


class BatchProcessor:
    """
    Process a directory of PDFs through the full compliance pipeline.

    Each file is reviewed independently in a thread pool so parsing (which
    uses pdfplumber's synchronous API) doesn't block the event loop.
    """

    def __init__(self, max_workers: int = config.BATCH_MAX_WORKERS) -> None:
        self.max_workers = max_workers
        self._executor   = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="batch")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        input_dir: Path,
        fmt: str = "all",
        output_dir: Optional[Path] = None,
        use_rag: bool = True,
    ) -> "BatchSummary":
        """
        Review all PDFs in `input_dir` concurrently.

        Returns a BatchSummary with per-file results and aggregate stats.
        """
        pdf_files = sorted(input_dir.glob("*.pdf"))
        if not pdf_files:
            raise ValueError(f"No PDF files found in {input_dir}")

        print(f"[BatchProcessor] Starting batch review: {len(pdf_files)} files, {self.max_workers} workers")
        started_at = datetime.now()

        # Fan out — process files in chunks to bound memory usage
        all_results: List[BatchJobResult] = []
        chunk_size  = config.BATCH_CHUNK_SIZE

        for i in range(0, len(pdf_files), chunk_size):
            chunk = pdf_files[i : i + chunk_size]
            tasks = [
                asyncio.get_event_loop().run_in_executor(
                    self._executor,
                    self._review_file,
                    fp, fmt, output_dir, use_rag,
                )
                for fp in chunk
            ]
            chunk_results = await asyncio.gather(*tasks, return_exceptions=False)
            all_results.extend(chunk_results)
            print(
                f"[BatchProcessor] Progress: {min(i + chunk_size, len(pdf_files))}/{len(pdf_files)} files"
            )

        elapsed = (datetime.now() - started_at).total_seconds()
        return BatchSummary(all_results, elapsed)

    async def run_texts(
        self,
        texts: List[Dict],   # [{"name": "...", "text": "..."}]
        fmt: str = "all",
        output_dir: Optional[Path] = None,
    ) -> "BatchSummary":
        """Review a list of raw-text project descriptions concurrently."""
        started_at = datetime.now()
        tasks = [
            asyncio.get_event_loop().run_in_executor(
                self._executor,
                self._review_text,
                item["name"], item["text"], fmt, output_dir,
            )
            for item in texts
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        elapsed = (datetime.now() - started_at).total_seconds()
        return BatchSummary(list(results), elapsed)

    # ------------------------------------------------------------------
    # Synchronous worker (runs inside ThreadPoolExecutor)
    # ------------------------------------------------------------------

    def _review_file(
        self,
        file_path: Path,
        fmt: str,
        output_dir: Optional[Path],
        use_rag: bool,
    ) -> BatchJobResult:
        result = BatchJobResult(file_path)
        t0     = datetime.now()

        try:
            from src.parser.pdf_parser       import PDFParser
            from src.parser.condition_extractor import ConditionExtractor
            from src.engine.decision_engine  import DecisionEngine
            from src.rag.generator           import AHJCommentGenerator
            from src.reports.report_generator import ReportWriter

            doc        = PDFParser().parse(file_path)
            conditions = ConditionExtractor().extract(doc)
            violations = DecisionEngine().evaluate(conditions)

            kb = None
            if use_rag:
                try:
                    from src.rag.knowledge_base import HCAIKnowledgeBase
                    kb = HCAIKnowledgeBase()
                    if kb.count() == 0:
                        kb.load_from_files()
                except Exception:
                    kb = None

            enriched = AHJCommentGenerator(knowledge_base=kb).enrich(violations)

            # Write to a per-file subdirectory under output_dir
            per_file_dir: Optional[Path] = None
            if output_dir:
                per_file_dir = output_dir / file_path.stem
                per_file_dir.mkdir(parents=True, exist_ok=True)

            paths = ReportWriter(output_dir=per_file_dir).write_all(
                enriched, conditions, project_name=file_path.stem
            )

            result.success         = True
            result.violation_count = len(enriched)
            result.critical_count  = sum(1 for v in enriched if getattr(v.violation, "severity", None) and v.violation.severity.name == "CRITICAL")
            result.output_paths    = {k: str(v) for k, v in paths.items()}

        except Exception as exc:
            result.success = False
            result.error   = f"{type(exc).__name__}: {exc}"
            print(f"[BatchProcessor] ERROR — {file_path.name}: {result.error}")

        result.duration_seconds = (datetime.now() - t0).total_seconds()
        return result

    def _review_text(
        self,
        name: str,
        text: str,
        fmt: str,
        output_dir: Optional[Path],
    ) -> BatchJobResult:
        """Same pipeline as _review_file but for raw text input."""
        result    = BatchJobResult(Path(name))
        result.file_path    = Path(name)
        result.project_name = name
        t0        = datetime.now()

        try:
            from src.parser.pdf_parser         import PDFParser
            from src.parser.condition_extractor import ConditionExtractor
            from src.engine.decision_engine    import DecisionEngine
            from src.rag.generator             import AHJCommentGenerator
            from src.reports.report_generator  import ReportWriter

            doc        = PDFParser().parse_text_input(text, source_name=name)
            conditions = ConditionExtractor().extract(doc)
            violations = DecisionEngine().evaluate(conditions)
            enriched   = AHJCommentGenerator().enrich(violations)

            per_file_dir: Optional[Path] = None
            if output_dir:
                per_file_dir = output_dir / name
                per_file_dir.mkdir(parents=True, exist_ok=True)

            paths = ReportWriter(output_dir=per_file_dir).write_all(
                enriched, conditions, project_name=name
            )

            result.success         = True
            result.violation_count = len(enriched)
            result.output_paths    = {k: str(v) for k, v in paths.items()}

        except Exception as exc:
            result.success = False
            result.error   = f"{type(exc).__name__}: {exc}"

        result.duration_seconds = (datetime.now() - t0).total_seconds()
        return result


class BatchSummary:
    """Aggregate statistics for a completed batch run."""

    def __init__(self, results: List[BatchJobResult], total_seconds: float) -> None:
        self.results         = results
        self.total_seconds   = total_seconds
        self.total_files     = len(results)
        self.succeeded       = sum(1 for r in results if r.success)
        self.failed          = sum(1 for r in results if not r.success)
        self.total_violations = sum(r.violation_count for r in results)
        self.total_critical   = sum(r.critical_count  for r in results)

    def to_dict(self) -> Dict:
        return {
            "summary": {
                "total_files":      self.total_files,
                "succeeded":        self.succeeded,
                "failed":           self.failed,
                "total_violations": self.total_violations,
                "total_critical":   self.total_critical,
                "total_seconds":    round(self.total_seconds, 2),
                "avg_seconds_per_file": round(
                    self.total_seconds / self.total_files, 2
                ) if self.total_files else 0,
            },
            "files": [r.to_dict() for r in self.results],
        }

    def print_summary(self) -> None:
        print(f"\n{'='*60}")
        print("BATCH REVIEW SUMMARY")
        print(f"{'='*60}")
        print(f"  Files processed : {self.total_files}")
        print(f"  Succeeded       : {self.succeeded}")
        print(f"  Failed          : {self.failed}")
        print(f"  Total violations: {self.total_violations}  ({self.total_critical} Critical)")
        print(f"  Total time      : {self.total_seconds:.1f}s")
        if self.failed:
            print(f"\n  Failed files:")
            for r in self.results:
                if not r.success:
                    print(f"    • {r.file_path.name}: {r.error}")
        print(f"{'='*60}\n")
