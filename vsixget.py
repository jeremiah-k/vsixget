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

    # Function to verify the downloaded file is a valid VSIX (ZIP) file
    def verify_vsix(file_path):
        """Verify that the downloaded file is a valid VSIX (ZIP) file."""
        try:
            # Check if file exists and is not empty
            if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                print("Error: Downloaded file is empty or does not exist.")
                return False

            # Try to open the file as a ZIP archive
            import zipfile
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                # Try to read the file list to verify it's a valid ZIP
                zip_ref.namelist()
            return True
        except zipfile.BadZipFile:
            print("Error: Downloaded file is not a valid VSIX (ZIP) file.")
            return False
        except Exception as e:
            print(f"Error verifying file: {e}")
            return False

    # Function to download with better error handling
    def download_file(url, output_path, description):
        """Download a file with better error handling and verification."""
        print(f"Trying {description}...")
        print(f"URL: {url}")

        # Create a temporary file for the download
        temp_path = f"{output_path}.tmp"

        # Remove any existing temporary file
        if os.path.exists(temp_path):
            os.remove(temp_path)

        try:
            # Download the file
            response = requests.get(url, stream=True)

            # Check if the request was successful
            if response.status_code == 200:
                # Get the total file size if available
                total_size = int(response.headers.get('content-length', 0))

                # Download with progress indication
                with open(temp_path, 'wb') as f:
                    if total_size > 0:
                        print(f"Downloading {total_size / (1024 * 1024):.2f} MB...")

                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

                # Verify the downloaded file
                if verify_vsix(temp_path):
                    # Move the temporary file to the final location
                    os.replace(temp_path, output_path)
                    print(f"Success! Downloaded to: {output_path}")
                    return True
                else:
                    # Remove the invalid file
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    print("Download completed but file verification failed.")
                    return False
            else:
                print(f"Download failed with status code: {response.status_code}")
                print(f"Response: {response.text[:500]}")  # Print first 500 chars of response
                return False
        except Exception as e:
            print(f"Download error: {e}")
            # Clean up partial download if it exists
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return False

    # Try platform-specific URL first
    platform_url = f"{base_url}?targetPlatform=linux-x64"
    print(f"Attempting to download {publisher}.{extension}{' version ' + version if version else ''}...")

    if download_file(platform_url, filepath, "platform-specific URL (linux-x64)"):
        return True

    # Fallback to universal package
    print("Fallback: trying universal package...")
    if download_file(base_url, filepath, "universal package"):
        return True

    # If we get here, both attempts failed
    print("Error: Failed to download extension. Please check the extension ID and version.")
    print("You might want to try downloading manually from the marketplace.")
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
