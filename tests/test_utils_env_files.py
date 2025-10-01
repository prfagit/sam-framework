import pytest
import os
import tempfile
from unittest.mock import patch, mock_open
from sam.utils.env_files import find_env_path, write_env_file


class TestEnvFiles:
    """Test environment file utilities."""

    @patch("os.getcwd")
    @patch("os.path.exists")
    def test_find_env_path_existing_cwd_env(self, mock_exists, mock_getcwd):
        """Test finding .env file when it exists in current working directory."""
        mock_getcwd.return_value = "/home/user/project"
        mock_exists.return_value = True

        result = find_env_path()

        assert result == "/home/user/project/.env"

    @patch("os.getcwd")
    @patch("os.path.exists")
    def test_find_env_path_repo_env_example(self, mock_exists, mock_getcwd):
        """Test finding .env file using repo .env.example pattern."""
        mock_getcwd.return_value = "/home/user/project"

        def exists_side_effect(path):
            if path == "/home/user/project/.env":
                return False
            elif path == "/home/user/project/sam_framework/.env.example":
                return True
            return False

        mock_exists.side_effect = exists_side_effect

        result = find_env_path()

        assert result == "/home/user/project/sam_framework/.env"

    @patch("os.getcwd")
    @patch("os.path.exists")
    def test_find_env_path_fallback_to_cwd(self, mock_exists, mock_getcwd):
        """Test falling back to CWD .env when other options don't exist."""
        mock_getcwd.return_value = "/home/user/project"
        mock_exists.return_value = False

        result = find_env_path()

        assert result == "/home/user/project/.env"

    @patch("os.getcwd")
    @patch("os.path.exists")
    def test_find_env_path_repo_structure(self, mock_exists, mock_getcwd):
        """Test finding .env in repo structure."""
        mock_getcwd.return_value = "/home/user/sam-framework"

        def exists_side_effect(path):
            if path == "/home/user/sam-framework/.env":
                return False
            elif path == "/home/user/sam-framework/sam_framework/.env.example":
                return True
            return False

        mock_exists.side_effect = exists_side_effect

        result = find_env_path()

        assert result == "/home/user/sam-framework/sam_framework/.env"

    def test_write_env_file_new_file(self):
        """Test writing a new .env file."""
        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as temp_file:
            temp_path = temp_file.name

        try:
            config_data = {
                "LLM_PROVIDER": "openai",
                "OPENAI_API_KEY": "sk-test123",
                "SAM_SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com",
            }

            write_env_file(temp_path, config_data)

            # Read back the file
            with open(temp_path, "r") as f:
                content = f.read()

            lines = content.strip().split("\n")

            # Check header
            assert lines[0] == "# SAM Framework configuration"
            assert lines[1] == "# Managed by CLI"
            assert lines[2] == ""

            # Check key-value pairs
            env_lines = [line for line in lines[3:] if line.strip()]
            assert "LLM_PROVIDER=openai" in env_lines
            assert "OPENAI_API_KEY=sk-test123" in env_lines
            assert "SAM_SOLANA_RPC_URL=https://api.mainnet-beta.solana.com" in env_lines

        finally:
            os.unlink(temp_path)

    def test_write_env_file_update_existing(self):
        """Test updating an existing .env file."""
        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as temp_file:
            temp_file.write("# Existing comment\n")
            temp_file.write("EXISTING_VAR=old_value\n")
            temp_file.write("LLM_PROVIDER=anthropic\n")
            temp_file.write("\n")
            temp_path = temp_file.name

        try:
            config_data = {
                "LLM_PROVIDER": "openai",  # Update existing
                "NEW_VAR": "new_value",  # Add new
                "EXISTING_VAR": "updated_value",  # Update existing
            }

            write_env_file(temp_path, config_data)

            # Read back the file
            with open(temp_path, "r") as f:
                content = f.read()

            lines = content.strip().split("\n")

            # Check that existing content is preserved and updated
            env_lines = [line for line in lines if "=" in line and not line.startswith("#")]
            env_dict = dict(line.split("=", 1) for line in env_lines)

            assert env_dict["LLM_PROVIDER"] == "openai"
            assert env_dict["NEW_VAR"] == "new_value"
            assert env_dict["EXISTING_VAR"] == "updated_value"

        finally:
            os.unlink(temp_path)

    def test_write_env_file_empty_values(self):
        """Test writing .env file with empty values."""
        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as temp_file:
            temp_path = temp_file.name

        try:
            config_data = {"EMPTY_VAR": "", "NORMAL_VAR": "value"}

            write_env_file(temp_path, config_data)

            # Read back the file
            with open(temp_path, "r") as f:
                content = f.read()

            lines = content.strip().split("\n")
            env_lines = [line for line in lines if "=" in line and not line.startswith("#")]

            assert "EMPTY_VAR=" in env_lines
            assert "NORMAL_VAR=value" in env_lines

        finally:
            os.unlink(temp_path)

    def test_write_env_file_special_characters(self):
        """Test writing .env file with special characters in values."""
        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as temp_file:
            temp_path = temp_file.name

        try:
            config_data = {
                "URL": "https://api.example.com/path?query=value&other=test",
                "COMPLEX_KEY": "sk-1234567890abcdef!@#$%^&*()",
                "MULTILINE": "line1\\nline2",
            }

            write_env_file(temp_path, config_data)

            # Read back the file
            with open(temp_path, "r") as f:
                content = f.read()

            lines = content.strip().split("\n")
            env_lines = [line for line in lines if "=" in line and not line.startswith("#")]

            assert "URL=https://api.example.com/path?query=value&other=test" in env_lines
            assert "COMPLEX_KEY=sk-1234567890abcdef!@#$%^&*()" in env_lines
            assert "MULTILINE=line1\\nline2" in env_lines

        finally:
            os.unlink(temp_path)

    @patch("builtins.open", new_callable=mock_open)
    def test_write_env_file_io_error(self, mock_file):
        """Test handling of IO errors when writing .env file."""
        mock_file.side_effect = IOError("Disk full")

        config_data = {"TEST_VAR": "test_value"}

        with pytest.raises(IOError, match="Disk full"):
            write_env_file("/nonexistent/path/.env", config_data)

    def test_write_env_file_malformed_existing(self):
        """Test handling of malformed existing .env file."""
        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as temp_file:
            temp_file.write("MALFORMED_LINE_WITHOUT_EQUALS\n")
            temp_file.write("VALID_VAR=valid_value\n")
            temp_file.write("ANOTHER_MALFORMED_LINE\n")
            temp_path = temp_file.name

        try:
            config_data = {"NEW_VAR": "new_value"}

            # Should not crash on malformed lines
            write_env_file(temp_path, config_data)

            # Read back the file
            with open(temp_path, "r") as f:
                content = f.read()

            lines = content.strip().split("\n")
            env_lines = [line for line in lines if "=" in line and not line.startswith("#")]

            # Should contain new variable and preserve valid existing one
            assert "NEW_VAR=new_value" in env_lines
            assert "VALID_VAR=valid_value" in env_lines

        finally:
            os.unlink(temp_path)

    def test_write_env_file_unicode_values(self):
        """Test writing .env file with Unicode values."""
        with tempfile.NamedTemporaryFile(mode="w+", delete=False, encoding="utf-8") as temp_file:
            temp_path = temp_file.name

        try:
            config_data = {"UNICODE_VAR": "héllo wörld 🌍", "EMOJI_VAR": "🤖 SAM Framework 🚀"}

            write_env_file(temp_path, config_data)

            # Read back the file
            with open(temp_path, "r", encoding="utf-8") as f:
                content = f.read()

            lines = content.strip().split("\n")
            env_lines = [line for line in lines if "=" in line and not line.startswith("#")]

            assert "UNICODE_VAR=héllo wörld 🌍" in env_lines
            assert "EMOJI_VAR=🤖 SAM Framework 🚀" in env_lines

        finally:
            os.unlink(temp_path)


if __name__ == "__main__":
    pytest.main([__file__])
