import os
import tempfile
import pytest
import logging
from pathlib import Path
from io import BytesIO
from fastapi import UploadFile
from unittest.mock import MagicMock

from app.services.docling_surya_ocr import DoclingSuryaOCRPipeline

logger = logging.getLogger(__name__)

def test_pipeline_initialization_with_path(tmp_path):
    # Create a dummy file
    dummy_file = tmp_path / "dummy.pdf"
    dummy_file.write_text("dummy pdf content")
    
    pipeline = DoclingSuryaOCRPipeline(dummy_file)
    assert pipeline.file_path == dummy_file
    assert pipeline.temp_file is None

def test_pipeline_initialization_with_upload_file():
    # Simulate an UploadFile
    filename = "test_upload.pdf"
    content = b"pdf binary content"
    file_like = BytesIO(content)
    
    upload_file = UploadFile(file=file_like, filename=filename)
    
    pipeline = DoclingSuryaOCRPipeline(upload_file)
    assert pipeline.file_path.exists()
    assert pipeline.file_path.suffix == ".pdf"
    assert pipeline.temp_file is not None
    
    # Read content from path to verify
    assert pipeline.file_path.read_bytes() == content
    
    # Verify cleanup on destruction
    temp_path = pipeline.file_path
    assert temp_path.exists()
    
    # Del the pipeline to trigger __del__
    del pipeline
    assert not temp_path.exists()

def test_layout_reconstruction_mock():
    # Mock Document and Converter
    pipeline = DoclingSuryaOCRPipeline.__new__(DoclingSuryaOCRPipeline)
    pipeline.file_path = Path("dummy.pdf")
    pipeline.temp_file = None
    
    # Create mock items with bboxes representing a multi-column layout
    # Row 1: "Header Left" (l=10, r=40) and "Header Right" (l=60, r=90)
    # Row 2: "Footer Center" (l=35, r=65)
    
    class MockBBox:
        def __init__(self, l, t, r, b, page=1):
            self.l = l
            self.t = t
            self.r = r
            self.b = b
            self.page_no = page
            
    class MockProv:
        def __init__(self, bbox):
            self.bbox = bbox
            self.page_no = 1
            
    class MockTextItem:
        def __init__(self, text, label, bbox):
            self.text = text
            self.label = label
            self.prov = [MockProv(bbox)]
            
    class MockPageSize:
        def __init__(self, w, h):
            self.width = w
            self.height = h
            
    class MockPage:
        def __init__(self, w, h):
            self.size = MockPageSize(w, h)
            
    mock_doc = MagicMock()
    mock_doc.pages = {1: MockPage(100.0, 200.0)}
    
    item1 = MockTextItem("Header Left", "paragraph", MockBBox(10.0, 20.0, 40.0, 30.0))
    item2 = MockTextItem("Header Right", "paragraph", MockBBox(60.0, 20.5, 90.0, 30.5)) # close top to item1 (t=20.5 vs 20.0)
    item3 = MockTextItem("Footer Center", "paragraph", MockBBox(35.0, 100.0, 65.0, 110.0))
    
    mock_doc.iterate_items.return_value = [(item1, 0), (item2, 0), (item3, 0)]
    
    mock_result = MagicMock()
    mock_result.document = mock_doc
    pipeline.converter = MagicMock(return_value=mock_result)
    
    # Reconstruct layout
    layout_text = pipeline.to_md()
    
    # Verify both rows are reconstructed
    assert "Header Left" in layout_text
    assert "Header Right" in layout_text
    assert "Footer Center" in layout_text
    
    # Let's check lines
    lines = layout_text.strip().split("\n")
    assert len(lines) == 2
    # First line should contain both Header Left and Header Right
    assert "Header Left" in lines[0] and "Header Right" in lines[0]
    # Second line should contain Footer Center
    assert "Footer Center" in lines[1]

@pytest.mark.skipif(not os.path.exists("sd2.jpg"), reason="sd2.jpg not found for integration testing")
def test_pipeline_conversion_integration():
    # Test with real sd2.jpg
    pipeline = DoclingSuryaOCRPipeline("sd2.jpg")
    
    try:
        # Run markdown export
        md_text = pipeline.to_md(save_file=True)
        assert isinstance(md_text, str)
        assert len(md_text) > 0
        
        # Check that .md file was created next to source
        md_file = Path("sd2.md")
        assert md_file.exists()
        
        # Run JSON export
        structure = pipeline.to_json(save_file=True)
        assert isinstance(structure, dict)
        assert "text" in structure
        assert "images" in structure
        assert "tables" in structure
        
        # Check that .json file was created
        json_file = Path("sd2.json")
        assert json_file.exists()
        
    except Exception as e:
        # If running in environment with limited GPU/CUDA memory, handle OOM gracefully
        if "CUDA out of memory" in str(e) or "OutOfMemoryError" in type(e).__name__:
            logger.warning(f"Skipping integration test due to CUDA out of memory: {e}")
            pytest.skip("Skipped integration test due to CUDA out of memory.")
        else:
            raise e
