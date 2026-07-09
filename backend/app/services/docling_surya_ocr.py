import os
import tempfile
import json
import logging
from pathlib import Path
from typing import Union, Dict, Any, List
from fastapi import UploadFile

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption, ImageFormatOption
from docling_surya import SuryaOcrOptions
from docling.datamodel.document import TableItem, PictureItem, TextItem

logger = logging.getLogger(__name__)

class DoclingSuryaOCRPipeline:
    """Document processing pipeline using Docling + Surya OCR with layout preservation."""

    def __init__(self, input_file: Union[str, Path, UploadFile]):
        self.input_file = input_file
        self.temp_file = None
        self.file_path = self._resolve_input_path()
        self._conversion_result = None

    def _resolve_input_path(self) -> Path:
        if isinstance(self.input_file, (str, Path)):
            path = Path(self.input_file)
            if not path.exists():
                raise FileNotFoundError(f"Input file not found: {path}")
            return path
        elif hasattr(self.input_file, "file") and hasattr(self.input_file, "filename"):
            # FastAPI UploadFile
            suffix = Path(self.input_file.filename).suffix or ".pdf"
            self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            
            # Read and write content
            self.input_file.file.seek(0)
            content = self.input_file.file.read()
            self.temp_file.write(content)
            self.temp_file.close()
            return Path(self.temp_file.name)
        else:
            raise TypeError("input_file must be a string path, Path object, or FastAPI UploadFile")

    def converter(self):
        """Runs the docling conversion using Surya OCR and returns the conversion result."""
        if self._conversion_result is not None:
            return self._conversion_result

        # Configure pipeline options for Surya OCR
        pipeline_options = PdfPipelineOptions(
            do_ocr=True,
            ocr_model="suryaocr",
            allow_external_plugins=True,
            ocr_options=SuryaOcrOptions(lang=["en"])  # Default to English
        )
        
        # Configure format options for PDF and Image format
        format_options = {
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=pipeline_options)
        }
        
        doc_converter = DocumentConverter(format_options=format_options)
        
        logger.info(f"Running DoclingSuryaOCR conversion on {self.file_path}")
        self._conversion_result = doc_converter.convert(self.file_path)
        return self._conversion_result

    def _reconstruct_layout(self) -> str:
        """Reconstructs the document's 2D layout page-by-page using element bounding boxes."""
        result = self.converter()
        doc = result.document
        
        # Gather all items with bounding boxes and group by page
        pages_items: Dict[int, List[Dict[str, Any]]] = {}
        
        for item, _level in doc.iterate_items():
            bbox = None
            if hasattr(item, "prov") and item.prov:
                for prov in item.prov:
                    if hasattr(prov, "bbox") and prov.bbox is not None:
                        b = prov.bbox
                        page_no = getattr(prov, "page_no", 1)
                        bbox = {
                            "l": float(b.l),
                            "t": float(b.t),
                            "r": float(b.r),
                            "b": float(b.b),
                            "page": int(page_no) - 1
                        }
                        break
            
            content = getattr(item, "text", "")
            if not content.strip():
                continue
                
            item_type = type(item).__name__
            label = getattr(item, "label", "text")
            
            # Use markdown representation for tables to preserve their structure
            if isinstance(item, TableItem) or label == "table":
                table_md = ""
                if hasattr(item, "export_to_dataframe"):
                    try:
                        df = item.export_to_dataframe(doc=doc)
                        table_md = df.to_markdown()
                    except Exception as e:
                        logger.warning(f"Error exporting table to dataframe: {e}")
                content = table_md or content
                
            elem = {
                "content": content,
                "bbox": bbox,
                "type": "table" if (isinstance(item, TableItem) or label == "table") else label
            }
            
            page_idx = bbox["page"] if bbox else 0
            pages_items.setdefault(page_idx, []).append(elem)
            
        reconstructed_pages = []
        
        # Process page by page
        for page_idx in sorted(pages_items.keys()):
            items = pages_items[page_idx]
            
            # Separate items with bboxes and items without bboxes
            items_with_bbox = [it for it in items if it["bbox"] is not None]
            items_without_bbox = [it for it in items if it["bbox"] is None]
            
            # Determine page dimensions
            page_obj = doc.pages.get(page_idx + 1)
            if page_obj and hasattr(page_obj, "size") and page_obj.size:
                W = float(page_obj.size.width)
                H = float(page_obj.size.height)
            else:
                # Fallback to max coordinates found
                W = max([it["bbox"]["r"] for it in items_with_bbox] + [612.0])
                H = max([it["bbox"]["b"] for it in items_with_bbox] + [792.0])
            
            # Group items with bboxes into horizontal rows based on vertical overlap
            # We use a y_tolerance of 8.0 points (standard line height is ~10-12 points)
            y_tolerance = 8.0
            rows: List[List[Dict[str, Any]]] = []
            
            # Sort items by top coordinate t first
            items_with_bbox.sort(key=lambda x: x["bbox"]["t"])
            
            for item in items_with_bbox:
                placed = False
                t = item["bbox"]["t"]
                
                # Try to place in an existing row if top coordinate is within y_tolerance of the row's average top
                for row in rows:
                    row_t_avg = sum(r["bbox"]["t"] for r in row) / len(row)
                    if abs(t - row_t_avg) <= y_tolerance:
                        row.append(item)
                        placed = True
                        break
                        
                if not placed:
                    rows.append([item])
            
            # Formatted page lines
            page_lines = []
            
            # Sort rows by top coordinate
            rows.sort(key=lambda r: sum(item["bbox"]["t"] for item in r) / len(r))
            
            # Render each row
            for row in rows:
                has_table = any(it["type"] == "table" for it in row)
                if has_table or len(row) == 1:
                    # Single element or table: render as is
                    row.sort(key=lambda x: x["bbox"]["l"])
                    for it in row:
                        page_lines.append(it["content"])
                else:
                    # Multi-column text: reconstruct layout using spaces
                    row.sort(key=lambda x: x["bbox"]["l"])
                    
                    row_str = ""
                    current_char_pos = 0
                    char_width_scale = 120.0  # Target 120 characters width page layout
                    
                    for it in row:
                        l_coord = it["bbox"]["l"]
                        content = it["content"]
                        
                        # Calculate starting character position proportional to page width
                        target_char_pos = int((l_coord / W) * char_width_scale)
                        
                        # Add padding spaces
                        spaces_needed = max(1, target_char_pos - current_char_pos)
                        row_str += " " * spaces_needed + content
                        current_char_pos = target_char_pos + len(content)
                        
                    page_lines.append(row_str)
                    
            # Append any items without bbox at the end of the page
            for it in items_without_bbox:
                page_lines.append(it["content"])
                
            reconstructed_pages.append("\n".join(page_lines))
            
        return "\n\n--- Page Break ---\n\n".join(reconstructed_pages)

    def to_md(self, save_file: bool = False) -> str:
        """Converts and exports to a layout-preserved Markdown text."""
        md_text = self._reconstruct_layout()
        
        if save_file:
            # Save file next to source file
            out_path = self.file_path.with_suffix(".md")
            out_path.write_text(md_text, encoding="utf-8")
            logger.info(f"Saved Markdown representation to {out_path}")
            
        return md_text

    def to_json(self, save_file: bool = False) -> Dict[str, Any]:
        """Converts and exports to JSON with bounding box coordinates for text, images, and tables."""
        result = self.converter()
        doc = result.document
        
        structure = {
            "text": [],
            "images": [],
            "tables": []
        }
        
        # Iterate through items to construct JSON with bbox
        for item, _level in doc.iterate_items():
            bbox = None
            if hasattr(item, "prov") and item.prov:
                for prov in item.prov:
                    if hasattr(prov, "bbox") and prov.bbox is not None:
                        b = prov.bbox
                        page_no = getattr(prov, "page_no", 1)
                        bbox = {
                            "l": float(b.l),
                            "t": float(b.t),
                            "r": float(b.r),
                            "b": float(b.b),
                            "page": int(page_no) - 1  # 0-indexed page number
                        }
                        break
            
            content = getattr(item, "text", "")
            
            if isinstance(item, TableItem) or getattr(item, "label", "") == "table":
                table_md = ""
                rows = []
                if hasattr(item, "export_to_dataframe"):
                    try:
                        df = item.export_to_dataframe(doc=doc)
                        table_md = df.to_markdown()
                        rows = df.values.tolist()
                    except Exception as e:
                        logger.warning(f"Error exporting table to dataframe: {e}")
                
                table_data = {
                    "content": content,
                    "markdown": table_md,
                    "rows": rows,
                    "bbox": bbox
                }
                structure["tables"].append(table_data)
                
            elif isinstance(item, PictureItem) or getattr(item, "label", "") in ("picture", "figure", "image"):
                image_data = {
                    "caption": content,
                    "bbox": bbox
                }
                structure["images"].append(image_data)
                
            else:
                if content.strip():
                    text_data = {
                        "type": getattr(item, "label", "text"),
                        "content": content.strip(),
                        "bbox": bbox
                    }
                    structure["text"].append(text_data)
        
        if save_file:
            out_path = self.file_path.with_suffix(".json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(structure, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved JSON representation to {out_path}")
            
        return structure

    def __del__(self):
        # Cleanup temp file
        if self.temp_file and os.path.exists(self.temp_file.name):
            try:
                os.unlink(self.temp_file.name)
            except Exception as e:
                logger.warning(f"Error cleaning up temp file {self.temp_file.name}: {e}")
