"""Additional tests for protocol_fetcher module to increase coverage."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date
from bs4 import BeautifulSoup
import httpx

from app.services.protocol_fetcher import (
    fetch_protocols_job,
    fetch_and_parse_protocols,
    download_pdf_text
)


class TestFetchProtocolsJob:
    """Tests for fetch_protocols_job function."""

    @pytest.mark.asyncio
    async def test_fetch_protocols_job_success(self, mock_db_session):
        """Test successful execution of fetch_protocols_job."""
        with patch('app.services.protocol_fetcher.calculate_sessionnet_params') as mock_params:
            mock_params.return_value = {'cjahr': 2024, 'cmonat': 1}
            
            with patch('app.services.protocol_fetcher.fetch_and_parse_protocols', new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = 5
                
                result = await fetch_protocols_job(mock_db_session)
                
                assert result == 5
                mock_fetch.assert_called_once_with({'cjahr': 2024, 'cmonat': 1}, mock_db_session)

    @pytest.mark.asyncio
    async def test_fetch_protocols_job_returns_count(self, mock_db_session):
        """Test that fetch_protocols_job returns the count of new protocols."""
        with patch('app.services.protocol_fetcher.calculate_sessionnet_params') as mock_params:
            mock_params.return_value = {}
            
            with patch('app.services.protocol_fetcher.fetch_and_parse_protocols', new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = 0
                
                result = await fetch_protocols_job(mock_db_session)
                
                assert result == 0


class TestFetchAndParseProtocols:
    """Tests for fetch_and_parse_protocols function."""

    @pytest.mark.asyncio
    async def test_fetch_and_parse_protocols_http_error(self, mock_db_session):
        """Test handling of HTTP error during fetch."""
        with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = httpx.HTTPError("Connection failed")
            
            result = await fetch_and_parse_protocols({}, mock_db_session)
            
            assert result == 0

    @pytest.mark.asyncio
    async def test_fetch_and_parse_protocols_empty_response(self, mock_db_session):
        """Test handling of empty response."""
        mock_response = MagicMock()
        mock_response.text = '<html><body></body></html>'
        
        with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            
            result = await fetch_and_parse_protocols({}, mock_db_session)
            
            assert result == 0

    @pytest.mark.asyncio
    async def test_fetch_and_parse_protocols_existing_protocol(self, mock_db_session):
        """Test skipping existing protocols."""
        html_content = '''
        <html>
            <table>
                <tr class="smc-t-r-l">
                    <td class="sidat_tag">01.01.2024</td>
                    <td class="silink">Test Title</td>
                    <td class="sidocs">
                        <i>NÖ</i>
                        <a href="getfile.asp?id=123">Protokoll</a>
                    </td>
                </tr>
            </table>
        </html>
        '''
        
        mock_response = MagicMock()
        mock_response.text = html_content
        
        # Mock existing protocol
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = MagicMock()  # Existing protocol
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            
            result = await fetch_and_parse_protocols({}, mock_db_session)
            
            assert result == 0

    @pytest.mark.asyncio
    async def test_fetch_and_parse_protocols_pdf_download_fails(self, mock_db_session):
        """Test handling when PDF download fails."""
        html_content = '''
        <html>
            <table>
                <tr class="smc-t-r-l">
                    <td class="sidat_tag">01.01.2024</td>
                    <td class="silink">Test Title</td>
                    <td class="sidocs">
                        <i>NÖ</i>
                        <a href="getfile.asp?id=123">Protokoll</a>
                    </td>
                </tr>
            </table>
        </html>
        '''
        
        mock_response = MagicMock()
        mock_response.text = html_content
        
        # Mock no existing protocol
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            
            with patch('app.services.protocol_fetcher.download_pdf_text', new_callable=AsyncMock) as mock_download:
                mock_download.return_value = None  # PDF download fails
                
                result = await fetch_and_parse_protocols({}, mock_db_session)
                
                assert result == 0

    @pytest.mark.asyncio
    async def test_fetch_and_parse_protocols_duplicate_detected(self, mock_db_session):
        """Test handling when duplicate is detected."""
        html_content = '''
        <html>
            <table>
                <tr class="smc-t-r-l">
                    <td class="sidat_tag">01.01.2024</td>
                    <td class="silink">Test Title</td>
                    <td class="sidocs">
                        <i>NÖ</i>
                        <a href="getfile.asp?id=123">Protokoll</a>
                    </td>
                </tr>
            </table>
        </html>
        '''
        
        mock_response = MagicMock()
        mock_response.text = html_content
        
        # Mock no existing protocol
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            
            with patch('app.services.protocol_fetcher.download_pdf_text', new_callable=AsyncMock) as mock_download:
                mock_download.return_value = "PDF content"
                
                with patch('app.services.protocol_fetcher.check_duplicate', new_callable=AsyncMock) as mock_check:
                    mock_check.return_value = True  # Duplicate detected
                    
                    result = await fetch_and_parse_protocols({}, mock_db_session)
                    
                    assert result == 0


class TestDownloadPdfText:
    """Tests for download_pdf_text function."""

    @pytest.mark.asyncio
    async def test_download_pdf_text_success(self):
        """Test successful PDF download and text extraction."""
        mock_response = MagicMock()
        mock_response.content = b'%PDF-1.4 mock pdf content'
        
        with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            
            with patch('fitz.open') as mock_fitz:
                mock_doc = MagicMock()
                mock_page = MagicMock()
                mock_page.get_text.return_value = "Extracted text"
                mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
                mock_doc.close = MagicMock()
                mock_fitz.return_value = mock_doc
                
                result = await download_pdf_text("http://example.com/test.pdf")
                
                assert result == "Extracted text"

    @pytest.mark.asyncio
    async def test_download_pdf_text_http_error(self):
        """Test handling of HTTP error."""
        with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = httpx.HTTPError("Connection failed")
            
            result = await download_pdf_text("http://example.com/test.pdf")
            
            assert result is None

    @pytest.mark.asyncio
    async def test_download_pdf_text_retry_then_success(self):
        """Test retry logic when first attempt fails."""
        mock_response = MagicMock()
        mock_response.content = b'%PDF-1.4 mock pdf content'
        
        with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = [
                httpx.HTTPError("First attempt failed"),
                mock_response
            ]
            
            with patch('fitz.open') as mock_fitz:
                mock_doc = MagicMock()
                mock_page = MagicMock()
                mock_page.get_text.return_value = "Extracted text"
                mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
                mock_doc.close = MagicMock()
                mock_fitz.return_value = mock_doc
                
                result = await download_pdf_text("http://example.com/test.pdf", max_retries=2)
                
                assert result == "Extracted text"

    @pytest.mark.asyncio
    async def test_download_pdf_text_all_retries_fail(self):
        """Test when all retries fail."""
        with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = httpx.HTTPError("Always fails")
            
            result = await download_pdf_text("http://example.com/test.pdf", max_retries=3)
            
            assert result is None
            assert mock_get.call_count == 3
