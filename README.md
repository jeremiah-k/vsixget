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

```bash
# Make the script executable
chmod +x vsixget.py

# Install required dependencies
pip install requests

# Optional: Move to a directory in your PATH
sudo cp vsixget.py /usr/local/bin/vsixget
```

## Usage

```bash
# Basic usage
./vsixget.py publisher.extension

# Specify version
./vsixget.py -v 1.2.3 publisher.extension

# Specify download directory
./vsixget.py -d ~/Downloads publisher.extension

# Download from marketplace URL
./vsixget.py https://marketplace.visualstudio.com/items?itemName=publisher.extension
```

## Examples

```bash
# Download the Python extension
./vsixget.py ms-python.python

# Download a specific version of the Python extension
./vsixget.py -v 2023.4.1 ms-python.python

# Download the Augment extension to the Downloads directory
./vsixget.py -d ~/Downloads augment.vscode-augment
```
