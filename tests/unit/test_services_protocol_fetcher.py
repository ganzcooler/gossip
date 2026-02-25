"""
Unit tests for app/services/protocol_fetcher.py
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from bs4 import BeautifulSoup

from app.services.protocol_fetcher import (
    parse_protocol_list,
    extract_getfile_id,
)


class TestExtractGetfileId:
    """Tests for extract_getfile_id function."""

    def test_extract_from_standard_url(self):
        """Test extracting getfile_id from standard SessionNet URL."""
        url = "https://sessionnet.example/getfile.asp?file=123&id=456"
        result = extract_getfile_id(url)
        assert result == 456

    def test_extract_from_simple_url(self):
        """Test extracting getfile_id from simple URL."""
        url = "getfile.asp?id=12345"
        result = extract_getfile_id(url)
        assert result == 12345

    def test_extract_with_multiple_params(self):
        """Test extracting getfile_id with multiple URL parameters."""
        url = "https://example.com/page?param1=value1&id=99999&param2=value2"
        result = extract_getfile_id(url)
        assert result == 99999

    def test_extract_at_start_of_query(self):
        """Test extracting getfile_id at start of query string."""
        url = "page?id=11111&other=value"
        result = extract_getfile_id(url)
        assert result == 11111

    def test_extract_large_number(self):
        """Test extracting large getfile_id."""
        url = "page?id=999999999"
        result = extract_getfile_id(url)
        assert result == 999999999

    def test_raises_error_when_not_found(self):
        """Test that ValueError is raised when getfile_id not found."""
        url = "https://example.com/page?otherparam=value"
        with pytest.raises(ValueError, match="Could not extract getfile_id"):
            extract_getfile_id(url)

    def test_raises_error_on_empty_string(self):
        """Test that ValueError is raised on empty string."""
        with pytest.raises(ValueError, match="Could not extract getfile_id"):
            extract_getfile_id("")

    def test_raises_error_on_malformed_url(self):
        """Test that ValueError is raised on malformed URL."""
        with pytest.raises(ValueError, match="Could not extract getfile_id"):
            extract_getfile_id("not a url")


class TestParseProtocolList:
    """Tests for parse_protocol_list function."""

    def test_parse_single_row(self):
        """Test parsing HTML with single protocol row."""
        html = """
        <html>
        <body>
            <table>
                <tr class="smc-t-r-l">
                    <td class="sidat_tag">15.01.2024</td>
                    <td class="silink"><a href="si0046.asp?sisessionid=123">Test Protocol Title</a></td>
                    <td class="sidocs">
                        <div>
                            <i>NÖ</i>
                            <a href="getfile.asp?id=12345">Protokoll</a>
                        </div>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, 'lxml')
        result = parse_protocol_list(soup)

        assert len(result) == 1
        assert result[0]['session_date'].day == 15
        assert result[0]['session_date'].month == 1
        assert result[0]['session_date'].year == 2024
        assert result[0]['title'] == "Test Protocol Title"
        assert result[0]['getfile_id'] == 12345

    def test_parse_multiple_rows(self):
        """Test parsing HTML with multiple protocol rows."""
        html = """
        <html>
        <body>
            <table>
                <tr class="smc-t-r-l">
                    <td class="sidat_tag">15.01.2024</td>
                    <td class="silink"><a href="si0046.asp?sisessionid=111">First Protocol</a></td>
                    <td class="sidocs">
                        <div>
                            <i>NÖ</i>
                            <a href="getfile.asp?id=11111">Protokoll</a>
                        </div>
                    </td>
                </tr>
                <tr class="smc-t-r-l">
                    <td class="sidat_tag">20.01.2024</td>
                    <td class="silink"><a href="si0046.asp?sisessionid=222">Second Protocol</a></td>
                    <td class="sidocs">
                        <div>
                            <i>NS</i>
                            <a href="getfile.asp?id=22222">Protokoll</a>
                        </div>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, 'lxml')
        result = parse_protocol_list(soup)

        assert len(result) == 2
        assert result[0]['title'] == "First Protocol"
        assert result[1]['title'] == "Second Protocol"

    def test_parse_both_row_classes(self):
        """Test that multiple rows with smc-t-r-l class are parsed."""
        html = """
        <html>
        <body>
            <table>
                <tr class="smc-t-r-l">
                    <td class="sidat_tag">15.01.2024</td>
                    <td class="silink"><a href="si0046.asp?sisessionid=1">Protocol 1</a></td>
                    <td class="sidocs">
                        <div>
                            <i>NÖ</i>
                            <a href="getfile.asp?id=1">Protokoll</a>
                        </div>
                    </td>
                </tr>
                <tr class="smc-t-r-l">
                    <td class="sidat_tag">16.01.2024</td>
                    <td class="silink"><a href="si0046.asp?sisessionid=2">Protocol 2</a></td>
                    <td class="sidocs">
                        <div>
                            <i>NÖ</i>
                            <a href="getfile.asp?id=2">Protokoll</a>
                        </div>
                    </td>
                </tr>
                <tr class="smc-t-r-l">
                    <td class="sidat_tag">17.01.2024</td>
                    <td class="silink"><a href="si0046.asp?sisessionid=3">Protocol 3</a></td>
                    <td class="sidocs">
                        <div>
                            <i>NÖ</i>
                            <a href="getfile.asp?id=3">Protokoll</a>
                        </div>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, 'lxml')
        result = parse_protocol_list(soup)

        assert len(result) == 3

    def test_skips_rows_with_missing_cells(self):
        """Test that rows without required class cells are skipped."""
        html = """
        <html>
        <body>
            <table>
                <tr class="smc-t-r-l">
                    <td>15.01.2024</td>
                    <td>Missing class cells</td>
                </tr>
                <tr class="smc-t-r-l">
                    <td class="sidat_tag">20.01.2024</td>
                    <td class="silink"><a href="si0046.asp?sisessionid=123">Valid Protocol</a></td>
                    <td class="sidocs">
                        <div>
                            <i>NÖ</i>
                            <a href="getfile.asp?id=12345">Protokoll</a>
                        </div>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, 'lxml')
        result = parse_protocol_list(soup)

        assert len(result) == 1
        assert result[0]['title'] == "Valid Protocol"

    def test_skips_rows_without_protocol_document(self):
        """Test that rows without protocol document link are skipped."""
        html = """
        <html>
        <body>
            <table>
                <tr class="smc-t-r-l">
                    <td class="sidat_tag">15.01.2024</td>
                    <td class="silink"><a href="si0046.asp?sisessionid=123">No Document Protocol</a></td>
                    <td class="sidocs">No protocol link here</td>
                </tr>
                <tr class="smc-t-r-l">
                    <td class="sidat_tag">20.01.2024</td>
                    <td class="silink"><a href="si0046.asp?sisessionid=456">Valid Protocol</a></td>
                    <td class="sidocs">
                        <div>
                            <i>NÖ</i>
                            <a href="getfile.asp?id=12345">Protokoll</a>
                        </div>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, 'lxml')
        result = parse_protocol_list(soup)

        assert len(result) == 1

    def test_handles_relative_urls(self):
        """Test that relative URLs are converted to absolute."""
        html = """
        <html>
        <body>
            <table>
                <tr class="smc-t-r-l">
                    <td class="sidat_tag">15.01.2024</td>
                    <td class="silink"><a href="si0046.asp?sisessionid=123">Test Protocol</a></td>
                    <td class="sidocs">
                        <div>
                            <i>NÖ</i>
                            <a href="getfile.asp?id=12345">Protokoll</a>
                        </div>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, 'lxml')
        result = parse_protocol_list(soup)

        assert result[0]['pdf_url'].startswith('http')

    def test_handles_absolute_urls(self):
        """Test that URLs are always prefixed with SESSIONNET_BASE_URL."""
        html = """
        <html>
        <body>
            <table>
                <tr class="smc-t-r-l">
                    <td class="sidat_tag">15.01.2024</td>
                    <td class="silink"><a href="si0046.asp?sisessionid=123">Test Protocol</a></td>
                    <td class="sidocs">
                        <div>
                            <i>NÖ</i>
                            <a href="getfile.asp?id=12345">Protokoll</a>
                        </div>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, 'lxml')
        result = parse_protocol_list(soup)

        # URL is always prefixed with base URL (even if already absolute)
        assert result[0]['pdf_url'].startswith('http')
        assert 'getfile.asp?id=12345' in result[0]['pdf_url']

    def test_returns_empty_list_when_no_rows(self):
        """Test that empty list is returned when no smc-t-r-l rows found."""
        html = """
        <html>
        <body>
            <table>
                <tr class="other-class"><td>No protocols here</td></tr>
            </table>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, 'lxml')
        result = parse_protocol_list(soup)

        assert result == []

    def test_handles_date_parsing_error(self):
        """Test that rows with invalid dates are skipped."""
        html = """
        <html>
        <body>
            <table>
                <tr class="smc-t-r-l">
                    <td class="sidat_tag">invalid-date</td>
                    <td class="silink"><a href="si0046.asp?sisessionid=123">Test Protocol</a></td>
                    <td class="sidocs">
                        <div>
                            <i>NÖ</i>
                            <a href="getfile.asp?id=12345">Protokoll</a>
                        </div>
                    </td>
                </tr>
                <tr class="smc-t-r-l">
                    <td class="sidat_tag">20.01.2024</td>
                    <td class="silink"><a href="si0046.asp?sisessionid=456">Valid Protocol</a></td>
                    <td class="sidocs">
                        <div>
                            <i>NÖ</i>
                            <a href="getfile.asp?id=67890">Protokoll</a>
                        </div>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, 'lxml')
        result = parse_protocol_list(soup)

        # Should skip invalid date row and parse valid one
        assert len(result) == 1
        assert result[0]['title'] == "Valid Protocol"
