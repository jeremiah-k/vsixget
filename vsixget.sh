#!/bin/bash

set -e

# Function to display help
show_help() {
    echo "Usage: $0 [options] <publisher.extension or marketplace URL>"
    echo
    echo "Options:"
    echo "  -h, --help                 Show this help message"
    echo "  -v, --version VERSION      Specify extension version"
    echo "  -d, --directory DIR        Directory to save the VSIX file (default: current directory)"
    echo
    echo "Examples:"
    echo "  $0 ms-python.python"
    echo "  $0 -v 2023.4.1 ms-python.python"
    echo "  $0 -d ~/Downloads https://marketplace.visualstudio.com/items?itemName=ms-python.python"
    echo
}

# Default values
download_dir="."
version=""

# Parse options
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        -v|--version)
            if [[ -z "$2" || "$2" == -* ]]; then
                echo "Error: Version option requires an argument"
                exit 1
            fi
            version="$2"
            shift 2
            ;;
        -d|--directory)
            if [[ -z "$2" || "$2" == -* ]]; then
                echo "Error: Directory option requires an argument"
                exit 1
            fi
            download_dir="$2"
            shift 2
            ;;
        *)
            # If it's the last argument, treat it as the extension identifier
            if [[ $# -eq 1 ]]; then
                extension_id="$1"
                shift
            else
                echo "Error: Unknown option $1"
                show_help
                exit 1
            fi
            ;;
    esac
done

# Check if extension identifier is provided
if [[ -z "$extension_id" ]]; then
    echo "Error: No extension identifier provided"
    show_help
    exit 1
fi

# Create download directory if it doesn't exist
if [[ ! -d "$download_dir" ]]; then
    mkdir -p "$download_dir"
fi

# Parse extension identifier (URL or publisher.extension format)
if [[ "$extension_id" == http* ]]; then
    # Extract publisher and extension from URL
    if [[ "$extension_id" =~ itemName=([^.]+)\.([^&]+) ]]; then
        publisher="${BASH_REMATCH[1]}"
        extension="${BASH_REMATCH[2]}"
    else
        echo "Error: Could not parse publisher and extension from URL"
        exit 1
    fi
else
    # Parse publisher.extension format
    IFS='.' read -r publisher extension <<< "$extension_id"
    if [[ -z "$publisher" || -z "$extension" ]]; then
        echo "Error: Invalid extension identifier format. Use 'publisher.extension' or a marketplace URL"
        exit 1
    fi
fi

# Prompt for version if not provided
if [[ -z "$version" ]]; then
    read -p "Enter version (leave blank for latest): " version
fi

# Construct base URL and get version information
if [[ -z "$version" ]]; then
    echo "Fetching latest version..."
    # Try to get the latest version information
    version_info=$(curl -s "https://marketplace.visualstudio.com/_apis/public/gallery/publishers/${publisher}/vsextensions/${extension}")

    # Extract version from the response if possible
    if [[ "$version_info" =~ \"version\":\"([^\"]+)\" ]]; then
        actual_version="${BASH_REMATCH[1]}"
        echo "Latest version: $actual_version"
        version="$actual_version"
    else
        echo "Could not determine latest version, using 'latest' in filename"
        actual_version="latest"
    fi

    base="https://marketplace.visualstudio.com/_apis/public/gallery/publishers/${publisher}/vsextensions/${extension}/latest/vspackage"
else
    actual_version="$version"
    base="https://marketplace.visualstudio.com/_apis/public/gallery/publishers/${publisher}/vsextensions/${extension}/${version}/vspackage"
fi

# Construct filename with version
filename="${publisher}.${extension}-${actual_version}.vsix"
filepath="${download_dir}/${filename}"

# Try with linux-x64 first, then fallback to universal
echo "Attempting to download ${publisher}.${extension}${version:+ version $version}..."

# Try platform-specific URL first
platform_url="${base}?targetPlatform=linux-x64"
echo "Trying platform-specific URL..."
if curl -f -L -o "$filepath" "$platform_url" 2>/dev/null; then
    echo "Success! Downloaded to: $filepath"
    exit 0
fi

# Fallback to universal package
echo "Fallback: trying universal package..."
if curl -f -L -o "$filepath" "$base" 2>/dev/null; then
    echo "Success! Downloaded to: $filepath"
    exit 0
fi

# If we get here, both attempts failed
echo "Error: Failed to download extension. Please check the extension ID and version."
# Clean up partial download if it exists
if [[ -f "$filepath" ]]; then
    rm "$filepath"
fi
exit 1
