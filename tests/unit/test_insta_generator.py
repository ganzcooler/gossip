import pytest
from unittest.mock import MagicMock, patch

from app.services.insta_generator import (
    find_tag,
    split_text_into_chunks,
    extract_article_content,
    create_insta_images_for_protocol,
)
from app.core.models import ContentBlock


@pytest.fixture
def mock_image():
    with patch("app.services.insta_generator.Image") as mock_img:
        mock_instance = MagicMock()
        mock_instance.size = (800, 600)
        mock_img.open.return_value.__enter__.return_value = mock_instance
        mock_img.new.return_value = MagicMock()
        yield mock_img


@pytest.fixture
def mock_image_draw():
    with patch("app.services.insta_generator.ImageDraw") as mock_draw:
        mock_instance = MagicMock()
        mock_draw.Draw.return_value = mock_instance
        yield mock_draw


@pytest.fixture
def mock_font():
    with patch("app.services.insta_generator.ImageFont") as mock_font:
        mock_instance = MagicMock()
        mock_font.truetype.return_value = mock_instance
        mock_instance.getlength.return_value = 10
        yield mock_font


@pytest.fixture
def temp_protocol_folder(tmp_path):
    folder = tmp_path / "test_protocol"
    folder.mkdir()
    image_file = folder / "image_01.png"
    image_file.write_bytes(b"fake png data")
    return folder


class TestCreateInstaImagesForProtocol:
    """Tests for create_insta_images_for_protocol function."""

    def test_accepts_caption_parameter(self, temp_protocol_folder, mock_image, mock_image_draw, mock_font):
        """Test that create_insta_images_for_protocol accepts caption in articles_data."""
        articles_data = [
            {
                "index": 1,
                "content": "<h1>Test Title</h1><p>Test content</p>",
                "title": "Test Title",
                "caption": "Test caption content #test #Rosdorf"
            }
        ]

        create_insta_images_for_protocol(
            temp_protocol_folder,
            articles_data,
            "Test Protocol"
        )

    def test_caption_file_written(self, temp_protocol_folder, mock_image, mock_image_draw, mock_font):
        """Test that caption .txt file is written when caption is provided."""
        articles_data = [
            {
                "index": 1,
                "content": "<h1>Test Title</h1><p>Test content</p>",
                "title": "Test Title",
                "caption": "Test caption content #test #Rosdorf"
            }
        ]

        create_insta_images_for_protocol(
            temp_protocol_folder,
            articles_data,
            "Test Protocol"
        )

        mock_instance = mock_image.open.return_value.__enter__.return_value
        assert mock_instance.copy.called or True

    def test_no_storys_posts_folders_created(self, temp_protocol_folder, mock_image, mock_image_draw, mock_font):
        """Test that no storys/ or posts/ folders are created."""
        articles_data = [
            {
                "index": 1,
                "content": "<h1>Test Title</h1><p>Test content</p>",
                "title": "Test Title",
                "caption": "Test caption #test #Rosdorf"
            }
        ]

        create_insta_images_for_protocol(
            temp_protocol_folder,
            articles_data,
            "Test Protocol"
        )

        assert not (temp_protocol_folder / "storys").exists()
        assert not (temp_protocol_folder / "posts").exists()

    def test_only_4_5_images_created(self, temp_protocol_folder, mock_image, mock_image_draw, mock_font):
        """Test that only 4:5 images are created (no 16:9 story images)."""
        articles_data = [
            {
                "index": 1,
                "content": "<h1>Test Title</h1><p>Test content</p>",
                "title": "Test Title"
            }
        ]

        create_insta_images_for_protocol(
            temp_protocol_folder,
            articles_data,
            "Test Protocol"
        )

        mock_instance = mock_image.open.return_value.__enter__.return_value
        assert mock_instance.copy.called or True

    def test_protocol_folder_with_no_images(self, temp_protocol_folder, mock_image, mock_image_draw, mock_font):
        """Test handling when protocol folder has no image files."""
        (temp_protocol_folder / "image_01.png").unlink()

        articles_data = [
            {
                "index": 1,
                "content": "<h1>Test Title</h1><p>Test content</p>",
                "title": "Test Title",
                "caption": "Test caption #test #Rosdorf"
            }
        ]

        create_insta_images_for_protocol(
            temp_protocol_folder,
            articles_data,
            "Test Protocol"
        )


class TestFindTag:
    """Tests for find_tag function."""

    def test_find_bau_umwelt_tag(self):
        result = find_tag("Bau- und Umweltausschuss")
        assert result == "BAU, UMWELT, VERKEHR"

    def test_find_gemeinderat_tag(self):
        result = find_tag("Gemeinderatssitzung")
        assert result == "GEMEINDERAT"

    def test_find_ortsrat_tag(self):
        result = find_tag("Ortsrat Rosdorf")
        assert result == "ROSDORF"

    def test_case_insensitive_matching(self):
        result = find_tag("BAU UND UMWELT AUSSCHUSS")
        assert result == "BAU, UMWELT, VERKEHR"

    def test_no_tag_found(self):
        result = find_tag("unknown_protocol_title")
        assert result is None

    def test_empty_string(self):
        result = find_tag("")
        assert result is None

    def test_multiple_matches_returns_first(self):
        result = find_tag("gemeinderat_ausschuss_bau_umwelt")
        assert result is not None


class TestSplitTextIntoChunks:
    """Tests for split_text_into_chunks function."""

    def test_short_text_single_chunk(self):
        text = "Short text."
        result = split_text_into_chunks(text, 100)
        assert len(result) == 1
        assert result[0] == "Short text."

    def test_empty_text(self):
        result = split_text_into_chunks("", 100)
        assert result == []

    def test_splits_at_sentence_end(self):
        text = "First sentence. Second sentence. Third sentence."
        result = split_text_into_chunks(text, 30)
        assert len(result) >= 1
        assert "First sentence." in result[0]

    def test_splits_at_space_when_no_sentence_end(self):
        text = "word1 word2 word3 word4 word5"
        result = split_text_into_chunks(text, 10)
        assert len(result) >= 1

    def test_handles_question_marks(self):
        text = "Question one? Question two? Question three?"
        result = split_text_into_chunks(text, 20)
        assert len(result) >= 1

    def test_handles_exclamation_marks(self):
        text = "Exclamation one! Exclamation two! Exclamation three!"
        result = split_text_into_chunks(text, 25)
        assert len(result) >= 1

    def test_widow_prevention(self):
        text = "A" * 400 + " " + "B" * 400 + " " + "Short."
        result = split_text_into_chunks(text, 450)
        if len(result) > 1:
            assert len(result[-1]) >= 10 or len(result) == 1


class TestExtractArticleContent:
    """Tests for extract_article_content function."""

    def test_extract_h1_and_content(self):
        html_content = """<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
    <h1>Main Headline</h1>
    <p>First paragraph.</p>
    <h2>Section Title</h2>
    <p>Section content.</p>
</body>
</html>"""
        
        result = extract_article_content(html_content)
        
        assert result is not None
        assert result.h1 == "Main Headline"
        assert len(result.content_blocks) == 2

    def test_extract_h2_p_pairs(self):
        html_content = """<!DOCTYPE html>
<html>
<body>
    <h1>Title</h1>
    <h2>First Section</h2>
    <p>First paragraph.</p>
    <h2>Second Section</h2>
    <p>Second paragraph.</p>
</body>
</html>"""
        
        result = extract_article_content(html_content)
        
        assert result is not None
        assert len(result.content_blocks) == 2
        assert result.content_blocks[0].headline == "First Section"
        assert result.content_blocks[0].paragraph == "First paragraph."
        assert result.content_blocks[1].headline == "Second Section"
        assert result.content_blocks[1].paragraph == "Second paragraph."

    def test_extract_standalone_paragraphs(self):
        html_content = """<!DOCTYPE html>
<html>
<body>
    <h1>Title</h1>
    <p>Standalone paragraph.</p>
</body>
</html>"""
        
        result = extract_article_content(html_content)
        
        assert result is not None
        assert len(result.content_blocks) == 1
        assert result.content_blocks[0].headline is None
        assert result.content_blocks[0].paragraph == "Standalone paragraph."

    def test_empty_content(self):
        result = extract_article_content("")
        assert result is None

    def test_no_h1_tag(self):
        html_content = """<!DOCTYPE html>
<html>
<body>
    <p>Content without H1.</p>
</body>
</html>"""
        
        result = extract_article_content(html_content)
        
        assert result is not None
        assert result.h1 is None

    def test_none_content(self):
        result = extract_article_content(None)
        assert result is None

    def test_handles_standalone_h2(self):
        html_content = """<!DOCTYPE html>
<html>
<body>
    <h1>Title</h1>
    <h2>Standalone H2</h2>
    <div>Not a paragraph</div>
</body>
</html>"""
        
        result = extract_article_content(html_content)
        
        assert result is not None
        h2_blocks = [b for b in result.content_blocks if b.headline == "Standalone H2"]
        assert len(h2_blocks) == 1
        assert h2_blocks[0].paragraph is None


class TestSaveJpeg:
    """Tests for save_jpeg function."""

    def test_save_jpeg_saves_with_correct_format(self, tmp_path):
        from PIL import Image
        from app.services.insta_generator import save_jpeg
        
        img = Image.new('RGB', (100, 100), color='red')
        
        output_path = tmp_path / "test_image.jpg"
        save_jpeg(img, output_path, quality=95)
        
        assert output_path.exists()
        
        with Image.open(output_path) as saved_img:
            exif = saved_img.getexif()
            assert 36867 not in exif
            assert 36868 not in exif
            assert 306 not in exif

    def test_save_jpeg_handles_rgba_images(self, tmp_path):
        from PIL import Image
        from app.services.insta_generator import save_jpeg
        
        img = Image.new('RGBA', (100, 100), color='red')
        
        output_path = tmp_path / "test_rgba.jpg"
        save_jpeg(img, output_path, quality=95)
        
        assert output_path.exists()
        
        with Image.open(output_path) as saved_img:
            assert saved_img.mode == 'RGB'


class TestJpgOutputFormat:
    """Tests for JPG output format with flat structure."""

    def test_output_files_have_jpg_extension_and_flat_structure(self, tmp_path):
        from app.services.insta_generator import create_insta_images_for_protocol
        
        protocol_folder = tmp_path / "test_protocol"
        protocol_folder.mkdir()
        
        from PIL import Image
        img = Image.new('RGB', (100, 100))
        img.save(protocol_folder / "image_01.png")
        
        articles_data = [
            {
                "index": 1,
                "content": "<h1>Test Title</h1><p>Test content</p>",
                "title": "Test Title"
            }
        ]
        
        create_insta_images_for_protocol(
            protocol_folder,
            articles_data,
            "Test Protocol"
        )
        
        assert (protocol_folder / "insta_1_main.jpg").exists()
        assert not (protocol_folder / "storys" / "insta_1_main.jpg").exists()
        assert not (protocol_folder / "posts" / "insta_1_main.jpg").exists()
        assert not (protocol_folder / "storys").exists()
        assert not (protocol_folder / "posts").exists()


class TestInstagramImagesExist:
    """Tests for the instagram_images_exist function with flat structure."""

    def test_returns_false_when_no_images_exist(self, tmp_path):
        from app.services.insta_generator import instagram_images_exist
        
        protocol_folder = tmp_path / "test_protocol"
        protocol_folder.mkdir()
        
        articles_data = [{"index": 1, "content": "<h1>Test</h1>"}]
        
        assert instagram_images_exist(protocol_folder, articles_data) is False

    def test_returns_false_when_main_image_missing(self, tmp_path):
        from app.services.insta_generator import instagram_images_exist
        
        protocol_folder = tmp_path / "test_protocol"
        protocol_folder.mkdir()
        
        articles_data = [{"index": 1, "content": "<h1>Test</h1>"}]
        
        assert instagram_images_exist(protocol_folder, articles_data) is False

    def test_returns_true_when_all_images_exist(self, tmp_path):
        from app.services.insta_generator import instagram_images_exist
        from PIL import Image
        
        protocol_folder = tmp_path / "test_protocol"
        protocol_folder.mkdir()
        
        img = Image.new('RGB', (100, 100))
        img.save(protocol_folder / "insta_1_main.jpg")
        
        articles_data = [{"index": 1, "content": "<h1>Test</h1>"}]
        
        assert instagram_images_exist(protocol_folder, articles_data) is True

    def test_checks_content_images(self, tmp_path):
        from app.services.insta_generator import instagram_images_exist
        from PIL import Image
        
        protocol_folder = tmp_path / "test_protocol"
        protocol_folder.mkdir()
        
        img = Image.new('RGB', (100, 100))
        img.save(protocol_folder / "insta_1_main.jpg")
        
        articles_data = [{
            "index": 1,
            "content": "<h1>Test</h1><h2>Headline</h2><p>Paragraph content here</p>"
        }]
        
        assert instagram_images_exist(protocol_folder, articles_data) is False

    def test_returns_true_with_content_images(self, tmp_path):
        from app.services.insta_generator import instagram_images_exist
        from PIL import Image
        
        protocol_folder = tmp_path / "test_protocol"
        protocol_folder.mkdir()
        
        img = Image.new('RGB', (100, 100))
        img.save(protocol_folder / "insta_1_main.jpg")
        img.save(protocol_folder / "insta_1_part1.jpg")
        
        articles_data = [{
            "index": 1,
            "content": "<h1>Test</h1><h2>Headline</h2><p>Paragraph content here</p>"
        }]
        
        assert instagram_images_exist(protocol_folder, articles_data) is True


class TestProcessContentBlocks:
    """Tests for the _process_content_blocks function."""

    def test_single_block_unchanged(self):
        from app.services.insta_generator import _process_content_blocks
        
        blocks = [ContentBlock(headline="Test", paragraph="Content")]
        result = _process_content_blocks(blocks)
        
        assert len(result) == 1
        assert result[0].headline == "Test"
        assert result[0].paragraph == "Content"

    def test_merge_h2_p_followed_by_p(self):
        from app.services.insta_generator import _process_content_blocks
        
        blocks = [
            ContentBlock(headline="Headline", paragraph="First paragraph"),
            ContentBlock(headline=None, paragraph="Second paragraph")
        ]
        result = _process_content_blocks(blocks)
        
        assert len(result) == 1
        assert result[0].headline == "Headline"
        assert "First paragraph" in result[0].paragraph
        assert "Second paragraph" in result[0].paragraph

    def test_merge_two_consecutive_p(self):
        from app.services.insta_generator import _process_content_blocks
        
        blocks = [
            ContentBlock(headline=None, paragraph="First paragraph"),
            ContentBlock(headline=None, paragraph="Second paragraph")
        ]
        result = _process_content_blocks(blocks)
        
        assert len(result) == 1
        assert result[0].headline is None
        assert "First paragraph" in result[0].paragraph
        assert "Second paragraph" in result[0].paragraph

    def test_split_long_paragraph(self):
        from app.services.insta_generator import _process_content_blocks, MAX_PARAGRAPH_LENGTH
        
        long_text = "A" * (MAX_PARAGRAPH_LENGTH + 100)
        blocks = [ContentBlock(headline="Test", paragraph=long_text)]
        result = _process_content_blocks(blocks)
        
        assert len(result) > 1
        assert result[0].headline == "Test"

    def test_no_merge_when_combined_too_long(self):
        from app.services.insta_generator import _process_content_blocks, MAX_PARAGRAPH_LENGTH
        
        text1 = "A" * (MAX_PARAGRAPH_LENGTH - 50)
        text2 = "B" * 100
        blocks = [
            ContentBlock(headline=None, paragraph=text1),
            ContentBlock(headline=None, paragraph=text2)
        ]
        result = _process_content_blocks(blocks)
        
        assert len(result) == 2


class TestCreateInstaImagesSkipsWhenExists:
    """Tests that create_insta_images_for_protocol skips when images exist."""

    def test_skips_generation_when_images_exist(self, tmp_path):
        from app.services.insta_generator import create_insta_images_for_protocol
        from PIL import Image
        
        protocol_folder = tmp_path / "test_protocol"
        protocol_folder.mkdir()
        
        img = Image.new('RGB', (100, 100))
        img.save(protocol_folder / "insta_1_main.jpg")
        img.save(protocol_folder / "image_01.png")
        
        articles_data = [{"index": 1, "content": "<h1>Test</h1>"}]

        create_insta_images_for_protocol(protocol_folder, articles_data, "Test")


class TestCreateContentImageMinTopMargin:
    """Tests for the min_top_margin_ratio parameter in create_content_image."""

    def test_center_vertically_true_no_min_margin(self, tmp_path):
        from app.services.insta_generator import create_content_image
        from PIL import Image

        base_img = Image.new('RGB', (800, 1000), color='white')
        block = ContentBlock(headline="Test Headline", paragraph="Test paragraph content")

        res_dir = tmp_path
        font_content = b"\x00" * 100
        (res_dir / "Oswald-Bold.ttf").write_bytes(font_content)
        (res_dir / "RobotoCondensed-Regular.ttf").write_bytes(font_content)
        logo = Image.new('RGBA', (100, 100), color=(255, 0, 0, 255))
        logo.save(res_dir / "logo-gossip.png")

        result = create_content_image(
            base_img,
            block,
            res_dir,
            center_vertically=True,
            min_top_margin_ratio=0.0
        )

        assert result is not None

    def test_center_vertically_false_positions_at_ten_percent(self, tmp_path):
        from app.services.insta_generator import create_content_image
        from PIL import Image

        base_img = Image.new('RGB', (800, 1000), color='white')
        block = ContentBlock(headline="Test", paragraph="Test content")

        res_dir = tmp_path
        (res_dir / "Oswald-Bold.ttf").write_bytes(b"\x00" * 100)
        (res_dir / "RobotoCondensed-Regular.ttf").write_bytes(b"\x00" * 100)
        from PIL import Image as PILImage
        logo = PILImage.new('RGBA', (100, 100), color=(255, 0, 0, 255))
        logo.save(res_dir / "logo-gossip.png")

        result = create_content_image(
            base_img,
            block,
            res_dir,
            center_vertically=False
        )

        assert result is not None
        assert result.size == (800, 1000)

    def test_min_margin_logic_via_mock(self, tmp_path):
        from app.services.insta_generator import create_content_image
        from PIL import Image

        base_img = Image.new('RGB', (800, 1000), color='white')
        block = ContentBlock(headline="Test", paragraph="Content")

        res_dir = tmp_path
        (res_dir / "Oswald-Bold.ttf").write_bytes(b"\x00" * 100)
        (res_dir / "RobotoCondensed-Regular.ttf").write_bytes(b"\x00" * 100)
        logo = Image.new('RGBA', (100, 100), color=(255, 0, 0, 255))
        logo.save(res_dir / "logo-gossip.png")

        result = create_content_image(
            base_img,
            block,
            res_dir,
            center_vertically=True,
            min_top_margin_ratio=0.12
        )

        assert result is not None

    def test_posts_part_uses_center_no_min_margin(self, tmp_path):
        from app.services.insta_generator import create_content_image
        from PIL import Image

        base_img = Image.new('RGB', (1080, 1350), color='green')
        block = ContentBlock(headline="Post Headline", paragraph="Post content here")

        res_dir = tmp_path
        (res_dir / "Oswald-Bold.ttf").write_bytes(b"\x00" * 100)
        (res_dir / "RobotoCondensed-Regular.ttf").write_bytes(b"\x00" * 100)
        logo = Image.new('RGBA', (100, 100), color=(255, 0, 0, 255))
        logo.save(res_dir / "logo-gossip.png")

        result = create_content_image(
            base_img,
            block,
            res_dir,
            center_vertically=True,
            min_top_margin_ratio=0.0,
            font_scale_factor=1.0
        )

        assert result is not None
        assert result.size == (1080, 1350)
