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
        url = "https://sessionnet.example/getfile.asp?file=123&id=456&getfile=78901"
        result = extract_getfile_id(url)
        assert result == 78901

    def test_extract_from_simple_url(self):
        """Test extracting getfile_id from simple URL."""
        url = "getfile.asp?getfile=12345"
        result = extract_getfile_id(url)
        assert result == 12345

    def test_extract_with_multiple_params(self):
        """Test extracting getfile_id with multiple URL parameters."""
        url = "https://example.com/page?param1=value1&getfile=99999&param2=value2"
        result = extract_getfile_id(url)
        assert result == 99999

    def test_extract_at_start_of_query(self):
        """Test extracting getfile_id at start of query string."""
        url = "page?getfile=11111&other=value"
        result = extract_getfile_id(url)
        assert result == 11111

    def test_extract_large_number(self):
        """Test extracting large getfile_id."""
        url = "page?getfile=999999999"
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
            <tr class="zl11">
                <td>15.01.2024</td>
                <td>10:00</td>
                <td>Test Protocol Title</td>
                <td><a href="getfile.asp?getfile=12345">PDF</a></td>
            </tr>
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
            <tr class="zl11">
                <td>15.01.2024</td>
                <td>10:00</td>
                <td>First Protocol</td>
                <td><a href="getfile.asp?getfile=11111">PDF</a></td>
            </tr>
            <tr class="zl12">
                <td>20.01.2024</td>
                <td>14:00</td>
                <td>Second Protocol</td>
                <td><a href="getfile.asp?getfile=22222">PDF</a></td>
            </tr>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, 'lxml')
        result = parse_protocol_list(soup)

        assert len(result) == 2
        assert result[0]['title'] == "First Protocol"
        assert result[1]['title'] == "Second Protocol"

    def test_parse_both_row_classes(self):
        """Test that both zl11 and zl12 classes are parsed."""
        html = """
        <html>
        <body>
            <tr class="zl11"><td>15.01.2024</td><td>10:00</td><td>Protocol 1</td><td><a href="getfile.asp?getfile=1">PDF</a></td></tr>
            <tr class="zl12"><td>16.01.2024</td><td>10:00</td><td>Protocol 2</td><td><a href="getfile.asp?getfile=2">PDF</a></td></tr>
            <tr class="zl11"><td>17.01.2024</td><td>10:00</td><td>Protocol 3</td><td><a href="getfile.asp?getfile=3">PDF</a></td></tr>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, 'lxml')
        result = parse_protocol_list(soup)

        assert len(result) == 3

    def test_skips_rows_with_insufficient_cells(self):
        """Test that rows with fewer than 4 cells are skipped."""
        html = """
        <html>
        <body>
            <tr class="zl11">
                <td>15.01.2024</td>
                <td>Test</td>
            </tr>
            <tr class="zl11">
                <td>20.01.2024</td>
                <td>10:00</td>
                <td>Valid Protocol</td>
                <td><a href="getfile.asp?getfile=12345">PDF</a></td>
            </tr>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, 'lxml')
        result = parse_protocol_list(soup)

        assert len(result) == 1
        assert result[0]['title'] == "Valid Protocol"

    def test_skips_rows_without_pdf_link(self):
        """Test that rows without PDF link are skipped."""
        html = """
        <html>
        <body>
            <tr class="zl11">
                <td>15.01.2024</td>
                <td>10:00</td>
                <td>No Link Protocol</td>
                <td>No link here</td>
            </tr>
            <tr class="zl11">
                <td>20.01.2024</td>
                <td>10:00</td>
                <td>Valid Protocol</td>
                <td><a href="getfile.asp?getfile=12345">PDF</a></td>
            </tr>
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
            <tr class="zl11">
                <td>15.01.2024</td>
                <td>10:00</td>
                <td>Test Protocol</td>
                <td><a href="getfile.asp?getfile=12345">PDF</a></td>
            </tr>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, 'lxml')
        result = parse_protocol_list(soup)

        assert result[0]['pdf_url'].startswith('http')

    def test_handles_absolute_urls(self):
        """Test that absolute URLs are preserved."""
        html = """
        <html>
        <body>
            <tr class="zl11">
                <td>15.01.2024</td>
                <td>10:00</td>
                <td>Test Protocol</td>
                <td><a href="https://example.com/getfile.asp?getfile=12345">PDF</a></td>
            </tr>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, 'lxml')
        result = parse_protocol_list(soup)

        assert result[0]['pdf_url'] == "https://example.com/getfile.asp?getfile=12345"

    def test_returns_empty_list_when_no_rows(self):
        """Test that empty list is returned when no protocol rows found."""
        html = """
        <html>
        <body>
            <div>No protocols here</div>
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
            <tr class="zl11">
                <td>invalid-date</td>
                <td>10:00</td>
                <td>Test Protocol</td>
                <td><a href="getfile.asp?getfile=12345">PDF</a></td>
            </tr>
            <tr class="zl11">
                <td>20.01.2024</td>
                <td>10:00</td>
                <td>Valid Protocol</td>
                <td><a href="getfile.asp?getfile=67890">PDF</a></td>
            </tr>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, 'lxml')
        result = parse_protocol_list(soup)

        # Should skip invalid date row and parse valid one
        assert len(result) == 1
        assert result[0]['title'] == "Valid Protocol"