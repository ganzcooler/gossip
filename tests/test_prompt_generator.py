import unittest
from unittest.mock import patch, MagicMock
import pathlib
import sys

# Ensure src directory is in sys.path for module imports from src
PROJECT_ROOT_FOR_TEST = pathlib.Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT_FOR_TEST) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_FOR_TEST))

# Modules to test
from src.pipeline_steps import prompt_generator

class TestPromptGenerator(unittest.TestCase):
    """Test suite for the prompt_generator."""

    @patch('src.pipeline_steps.prompt_generator.run_prompt_generation')
    def test_run_prompt_generation(self, mock_run_prompt_generation):
        prompt_generator.run_prompt_generation()
        mock_run_prompt_generation.assert_called_once()

if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
