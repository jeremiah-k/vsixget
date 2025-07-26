# vsixget

A Python tool for downloading VSIX files from the Visual Studio Marketplace.

## Features

- Download VS Code extensions directly from the marketplace
- Support for both direct extension IDs and marketplace URLs
- Specify version or download the latest
- Choose download directory
- Network connectivity checking before downloads
- Automatic retry logic with progressive delays
- Real-time download progress with MB and percentage indicators
- Reliable file integrity verification
- Universal package downloads for maximum compatibility

## Installation

### From PyPI (Recommended)

**Using pipx (recommended for CLI tools):**
```bash
# Install pipx if you don't have it
# See: https://pipx.pypa.io/stable/installation/

# Install vsixget with pipx
pipx install vsixget
```

**Using pip:**
```bash
# Install from PyPI
pip install vsixget
```

> **Note:** [pipx](https://pipx.pypa.io/stable/) is recommended for installing CLI tools as it creates isolated environments and makes the tools available globally. See the [pipx installation guide](https://pipx.pypa.io/stable/installation/) for platform-specific instructions.

### From Source

```bash
# Clone the repository
git clone https://github.com/jeremiah-k/vsixget.git
cd vsixget

# Make the script executable
chmod +x vsixget.py

# Create and activate a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate

# Install required dependencies
pip install requests
```

## Usage

```bash
# Basic usage
vsixget publisher.extension

# Download latest version without prompting
vsixget --latest publisher.extension

# Specify version
vsixget -v 1.2.3 publisher.extension

# Specify download directory
vsixget -d ~/Downloads publisher.extension

# Download from marketplace URL
vsixget https://marketplace.visualstudio.com/items?itemName=publisher.extension
```

## Examples

```bash
# Download the Python extension
vsixget ms-python.python

# Download latest version without prompting
vsixget --latest ms-python.python

# Download a specific version of the Python extension
vsixget -v 2023.4.1 ms-python.python

# Download the Augment extension to the Downloads directory
vsixget -d ~/Downloads augment.vscode-augment
```
