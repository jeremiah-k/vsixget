#!/usr/bin/env python3

import argparse
import os
import re
import sys
from urllib.parse import urlparse, parse_qs
import requests


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download VS Code extensions from the Visual Studio Marketplace",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s ms-python.python
  %(prog)s -v 2023.4.1 ms-python.python
  %(prog)s -d ~/Downloads https://marketplace.visualstudio.com/items?itemName=ms-python.python
        """
    )

    parser.add_argument(
        "extension_id",
        help="Extension identifier (publisher.extension) or marketplace URL"
    )

    parser.add_argument(
        "-v", "--version",
        help="Extension version (if not specified, latest version will be used)"
    )

    parser.add_argument(
        "-d", "--directory",
        default=".",
        help="Directory to save the VSIX file (default: current directory)"
    )

    return parser.parse_args()


def parse_extension_id(extension_id):
    """Parse extension ID from either a URL or publisher.extension format."""
    if extension_id.startswith(("http://", "https://")):
        # Parse from URL
        parsed_url = urlparse(extension_id)
        query_params = parse_qs(parsed_url.query)

        if "itemName" in query_params:
            item_name = query_params["itemName"][0]
            match = re.match(r"([^.]+)\.(.+)", item_name)

            if match:
                return match.group(1), match.group(2)
    else:
        # Parse from publisher.extension format
        parts = extension_id.split(".", 1)
        if len(parts) == 2:
            return parts[0], parts[1]

    return None, None


def download_extension(publisher, extension, version, directory):
    """Download the extension from the marketplace."""
    # Create directory if it doesn't exist
    os.makedirs(directory, exist_ok=True)

    # Get version information and construct base URL
    if not version:
        print("No version specified, fetching latest...")
        try:
            # Try to get the latest version information
            api_url = f"https://marketplace.visualstudio.com/_apis/public/gallery/publishers/{publisher}/vsextensions/{extension}"
            response = requests.get(api_url)
            if response.status_code == 200:
                data = response.json()
                if 'versions' in data and len(data['versions']) > 0:
                    actual_version = data['versions'][0]['version']
                    print(f"Latest version: {actual_version}")
                    version = actual_version
                else:
                    print("Could not determine latest version, using 'latest' in filename")
                    actual_version = "latest"
            else:
                print("Could not fetch version information, using 'latest' in filename")
                actual_version = "latest"
        except Exception as e:
            print(f"Error fetching version information: {e}")
            actual_version = "latest"

        base_url = f"https://marketplace.visualstudio.com/_apis/public/gallery/publishers/{publisher}/vsextensions/{extension}/latest/vspackage"
    else:
        actual_version = version
        base_url = f"https://marketplace.visualstudio.com/_apis/public/gallery/publishers/{publisher}/vsextensions/{extension}/{version}/vspackage"

    # Construct filename with version
    filename = f"{publisher}.{extension}-{actual_version}.vsix"
    filepath = os.path.join(directory, filename)

    # Try platform-specific URL first
    platform_url = f"{base_url}?targetPlatform=linux-x64"
    print(f"Attempting to download {publisher}.{extension}{' version ' + version if version else ''}...")
    print("Trying platform-specific URL...")

    try:
        response = requests.get(platform_url, stream=True)
        if response.status_code == 200:
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"Success! Downloaded to: {filepath}")
            return True
    except Exception as e:
        print(f"Platform-specific download failed: {e}")

    # Fallback to universal package
    print("Fallback: trying universal package...")
    try:
        response = requests.get(base_url, stream=True)
        if response.status_code == 200:
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"Success! Downloaded to: {filepath}")
            return True
    except Exception as e:
        print(f"Universal download failed: {e}")

    # If we get here, both attempts failed
    print("Error: Failed to download extension. Please check the extension ID and version.")
    # Clean up partial download if it exists
    if os.path.exists(filepath):
        os.remove(filepath)

    return False


def main():
    args = parse_args()

    publisher, extension = parse_extension_id(args.extension_id)

    if not publisher or not extension:
        print("Error: Could not parse publisher and extension from input")
        print(f"Input was: {args.extension_id}")
        print("Please use format 'publisher.extension' or a marketplace URL")
        sys.exit(1)

    # If version is not provided and we're in interactive mode, prompt for it
    version = args.version
    if not version and sys.stdin.isatty():
        version = input("Enter version (leave blank for latest): ")

    success = download_extension(publisher, extension, version, args.directory)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
