"""The production API origin must serve the same local brand art as Vite."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.config import STATIC_DIR


@pytest.mark.skipif(not (STATIC_DIR/'asset-icons').is_dir(),reason='frontend production build unavailable')
def test_brand_icons_are_public_svg_files_and_missing_icons_stay_404():
    with TestClient(app) as client:
        for brand in ('bitcoin','apple','semiconductor-manufacturing-international','shenzhen-inovance'):
            response=client.get(f'/asset-icons/{brand}.svg')
            assert response.status_code==200
            assert response.headers['content-type'].startswith('image/svg+xml')
            assert '<svg' in response.text
        missing=client.get('/asset-icons/not-a-real-brand.svg')
        assert missing.status_code==404
        assert '<!doctype html' not in missing.text.lower()
