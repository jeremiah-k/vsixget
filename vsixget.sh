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
    if [[ "$version_info" =~ \"versions\":\[\{\"version\":\"([^\"]+)\" ]]; then
        actual_version="${BASH_REMATCH[1]}"
        echo "Latest version: $actual_version"
        version="$actual_version"
    elif [[ "$version_info" =~ \"version\":\"([^\"]+)\" ]]; then
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

# Function to verify the downloaded file is a valid VSIX (ZIP) file
verify_vsix() {
    local file="$1"

    # Check if file exists and is not empty
    if [[ ! -f "$file" || ! -s "$file" ]]; then
        echo "Error: Downloaded file is empty or does not exist."
        return 1
    fi

    # Check if the file is a valid ZIP archive
    if command -v unzip &> /dev/null; then
        if ! unzip -t "$file" &> /dev/null; then
            echo "Error: Downloaded file is not a valid VSIX (ZIP) file."
            return 1
        fi
    else
        # If unzip is not available, use hexdump to check for ZIP signature
        if ! hexdump -n 4 -e '4/1 "%02X"' "$file" | grep -q "504B0304"; then
            echo "Error: Downloaded file does not have a valid ZIP signature."
            return 1
        fi
    fi

    return 0
}

# Function to download with better error handling
download_file() {
    local url="$1"
    local output="$2"
    local description="$3"

    echo "Trying $description..."
    echo "URL: $url"

    # Create a temporary file for the download
    local temp_file="${output}.tmp"

    # Remove any existing temporary file
    if [[ -f "$temp_file" ]]; then
        rm "$temp_file"
    fi

    # Create a temporary file for the response headers
    local headers_file=$(mktemp)

    # Download with curl, showing progress and saving headers
    # Note: We're not using -f here to allow handling of error responses
    if curl -L -D "$headers_file" --progress-bar -o "$temp_file" "$url"; then
        # Verify the downloaded file
        if verify_vsix "$temp_file"; then
            # Move the temporary file to the final location
            mv "$temp_file" "$output"
            echo "Success! Downloaded to: $output"
            rm "$headers_file"
            return 0
        else
            # Remove the invalid file
            rm "$temp_file"
            echo "Download completed but file verification failed."

            # Check if we got a JSON error response
            if grep -q "Content-Type: application/json" "$headers_file"; then
                echo "Server returned a JSON response instead of a VSIX file:"
                cat "$temp_file" | head -20  # Show first 20 lines of the response
            fi

            rm "$headers_file"
            return 1
        fi
    else
        local curl_exit_code=$?
        echo "Download failed with curl exit code: $curl_exit_code"

        # Check if we have an HTTP error status code
        if grep -q "HTTP/" "$headers_file"; then
            local status_code=$(grep "HTTP/" "$headers_file" | tail -1 | awk '{print $2}')
            echo "HTTP Status Code: $status_code"

            # If we have a response body, show it
            if [[ -f "$temp_file" && -s "$temp_file" ]]; then
                echo "Response body:"
                cat "$temp_file" | head -20  # Show first 20 lines of the response
            fi
        fi

        # Remove the failed download if it exists
        if [[ -f "$temp_file" ]]; then
            rm "$temp_file"
        fi

        rm "$headers_file"
        return 1
    fi
}

# Try platform-specific URL first
platform_url="${base}?targetPlatform=linux-x64"
if download_file "$platform_url" "$filepath" "platform-specific URL (linux-x64)"; then
    exit 0
fi

# Fallback to universal package
echo "Fallback: trying universal package..."
if download_file "$base" "$filepath" "universal package"; then
    exit 0
fi

# If we get here, both attempts failed
echo "Error: Failed to download extension. Please check the extension ID and version."
echo "You might want to try downloading manually from the marketplace."
exit 1
