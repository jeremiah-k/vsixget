# vsixget

A tool for downloading VSIX files from the Visual Studio Marketplace.

## Features

- Download VS Code extensions directly from the marketplace
- Support for both direct extension IDs and marketplace URLs
- Specify version or download the latest
- Choose download directory
- Available in both Bash and Python versions

## Why Two Implementations?

This project provides both Bash and Python implementations for different use cases:

### Bash Script (`vsixget.sh`)
- **Pros**: Minimal dependencies, available on most Unix-like systems without additional installation
- **Cons**: Limited error handling and URL parsing capabilities
- **Best for**: Quick use on systems where you don't want to install additional dependencies

### Python Script (`vsixget.py`)
- **Pros**: More robust error handling, better URL parsing, and more reliable HTTP requests
- **Cons**: Requires Python and the requests library
- **Best for**: Regular use, complex URLs, or when reliability is critical

Choose the implementation that best fits your environment and requirements.

## Installation

### Bash Version

```bash
# Make the script executable
chmod +x vsixget.sh

# Optional: Move to a directory in your PATH
sudo cp vsixget.sh /usr/local/bin/vsixget
```

### Python Version

```bash
# Make the script executable
chmod +x vsixget.py

# Install required dependencies
pip install requests

# Optional: Move to a directory in your PATH
sudo cp vsixget.py /usr/local/bin/vsixget
```

## Usage

### Bash Version

```bash
# Basic usage
./vsixget.sh publisher.extension

# Specify version
./vsixget.sh -v 1.2.3 publisher.extension

# Specify download directory
./vsixget.sh -d ~/Downloads publisher.extension

# Download from marketplace URL
./vsixget.sh https://marketplace.visualstudio.com/items?itemName=publisher.extension
```

### Python Version

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
./vsixget.sh ms-python.python

# Download a specific version of the Python extension
./vsixget.sh -v 2023.4.1 ms-python.python

# Download the Augment extension to the Downloads directory
./vsixget.sh -d ~/Downloads augment.vscode-augment
```
