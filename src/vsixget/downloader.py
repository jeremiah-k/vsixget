#!/usr/bin/env python3

import argparse
import hashlib
import os
import re
import sys
import time
import zipfile
from urllib.parse import parse_qs, urlparse

import requests
from packaging.version import parse as parse_version

# Import version from package __init__.py
try:
    from . import __version__
except ImportError:
    # Fallback for when running as script directly
    __version__ = "1.0.0"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download VS Code extensions from the Visual Studio Marketplace",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s ms-python.python
  %(prog)s --latest ms-python.python
  %(prog)s -v 2023.4.1 ms-python.python
  %(prog)s -d ~/Downloads https://marketplace.visualstudio.com/items?itemName=ms-python.python
        """,
    )

    parser.add_argument(
        "extension_id",
        help="Extension identifier (publisher.extension) or marketplace URL",
    )

    parser.add_argument(
        "-v",
        "--version",
        help="Extension version (if not specified, latest version will be used)",
    )

    parser.add_argument(
        "--latest",
        action="store_true",
        help="Download the latest version without prompting (same as not specifying a version)",
    )

    parser.add_argument(
        "-d",
        "--directory",
        default=".",
        help="Directory to save the VSIX file (default: current directory)",
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


def check_network_connectivity():
    """Check if we can reach the VS Code marketplace."""
    print("Checking network connectivity...")
    try:
        response = requests.get("https://marketplace.visualstudio.com", timeout=10)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


def version_compare(version1, version2):
    """Compare two version strings. Returns True if version1 < version2.

    Uses packaging.version.parse for robust version parsing that handles
    pre-releases and follows PEP 440 standards.
    """
    return parse_version(version1) < parse_version(version2)


def check_for_updates():
    """Check if a newer version of vsixget is available on GitHub."""
    try:
        # Get the latest release from GitHub API
        response = requests.get(
            "https://api.github.com/repos/jeremiah-k/vsixget/releases/latest", timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            latest_version = data.get("tag_name", "").lstrip("v")

            if latest_version and version_compare(__version__, latest_version):
                print(
                    f"📦 A newer version of vsixget is available: {latest_version} (current: {__version__})"
                )
                print("💡 Update with: pipx upgrade vsixget")
                print()

    except requests.exceptions.RequestException:
        # Silently fail if we can't check for updates
        pass


def download_extension(publisher, extension, version, directory):
    """Download the extension from the marketplace."""
    # Expand user directory path (handle ~ in paths)
    directory = os.path.expanduser(directory)

    # Create directory if it doesn't exist
    os.makedirs(directory, exist_ok=True)

    # Check network connectivity first
    if not check_network_connectivity():
        print(
            "Error: Cannot reach VS Code marketplace. Please check your internet connection."
        )
        return False

    # Get version information and construct base URL
    if not version:
        print("No version specified, fetching latest...")
        try:
            # Try to get the latest version information using the extensionquery API
            api_url = "https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery"
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json;api-version=3.0-preview.1",
            }
            payload = {
                "filters": [
                    {
                        "criteria": [
                            {"filterType": 7, "value": f"{publisher}.{extension}"}
                        ]
                    }
                ],
                "flags": 914,
            }
            response = requests.post(api_url, json=payload, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()

                # Extract nested data with try/except for cleaner error handling
                actual_version = "latest"
                try:
                    versions = data["results"][0]["extensions"][0]["versions"]

                    # Find the first version without a targetPlatform (universal version)
                    universal_version = next(
                        (v["version"] for v in versions if "targetPlatform" not in v),
                        None,
                    )

                    if universal_version:
                        actual_version = universal_version
                    elif versions:
                        # Fallback to the first version if no universal version is found
                        actual_version = versions[0]["version"]

                    print(f"Latest version: {actual_version}")

                except (KeyError, IndexError, TypeError):
                    print("Could not determine latest version, using 'latest' in filename")
            else:
                print("Could not fetch version information, using 'latest' in filename")
                actual_version = "latest"
        except requests.exceptions.RequestException as e:
            print(f"Error fetching version information: {e}")
            actual_version = "latest"

        # Use specific version URL if we detected the version, otherwise use latest
        if actual_version != "latest":
            base_url = f"https://marketplace.visualstudio.com/_apis/public/gallery/publishers/{publisher}/vsextensions/{extension}/{actual_version}/vspackage"
        else:
            base_url = f"https://marketplace.visualstudio.com/_apis/public/gallery/publishers/{publisher}/vsextensions/{extension}/latest/vspackage"
    else:
        actual_version = version
        base_url = f"https://marketplace.visualstudio.com/_apis/public/gallery/publishers/{publisher}/vsextensions/{extension}/{version}/vspackage"

    # Construct filename with version
    filename = f"{publisher}.{extension}-{actual_version}.vsix"
    filepath = os.path.join(directory, filename)

    # Function to verify the downloaded file is a valid VSIX (ZIP) file
    def verify_vsix(file_path, expected_size=None):
        """Verify that the downloaded file is a valid VSIX (ZIP) file with integrity checks."""
        try:
            # Check if file exists and is not empty
            if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                print("Error: Downloaded file is empty or does not exist.")
                return False

            # Check file size if expected size is provided (allow some tolerance for compression)
            if expected_size is not None:
                actual_size = os.path.getsize(file_path)
                # Allow 10% tolerance for size differences due to compression/headers
                tolerance = max(expected_size * 0.1, 1024)  # At least 1KB tolerance
                if abs(actual_size - expected_size) > tolerance:
                    print(f"Warning: File size differs significantly. Expected {expected_size}, got {actual_size}")
                    # Don't fail on size mismatch, just warn - the ZIP integrity check is more important

            # Try to open the file as a ZIP archive and test integrity
            with zipfile.ZipFile(file_path, "r") as zip_ref:
                # Test ZIP file integrity
                if zip_ref.testzip() is not None:
                    print("Error: Downloaded VSIX file is corrupted.")
                    return False
                # Try to read the file list to verify it's a valid ZIP
                zip_ref.namelist()
            return True
        except zipfile.BadZipFile:
            print("Error: Downloaded file is not a valid VSIX (ZIP) file.")
            return False
        except OSError as e:
            print(f"Error verifying file: {e}")
            return False

    def calculate_sha256(file_path):
        """Calculate SHA-256 hash of a file."""
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                # Read file in chunks to handle large files efficiently
                for chunk in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(chunk)
            return sha256_hash.hexdigest()
        except OSError as e:
            print(f"Error calculating file hash: {e}")
            return None

    # Function to download with retry logic and better progress reporting
    def download_file_with_retry(url, output_path, max_attempts=3):
        """Download a file with retry logic and improved progress reporting."""
        print("Trying universal package...")
        print(f"URL: {url}")

        for attempt in range(1, max_attempts + 1):
            print(f"Download attempt {attempt}/{max_attempts}...")

            # Create a temporary file for the download
            temp_path = f"{output_path}.tmp"

            # Remove any existing temporary file
            if os.path.exists(temp_path):
                os.remove(temp_path)

            try:
                # Download the file
                response = requests.get(url, stream=True, timeout=30)
                print(f"Response status code: {response.status_code}")

                # Check if the request was successful
                if response.status_code == 200:
                    # Get the total file size if available
                    total_size = int(response.headers.get("content-length", 0))
                    downloaded_size = 0

                    # Download with progress indication
                    with open(temp_path, "wb") as f:
                        if total_size > 0:
                            print(f"Downloading {total_size / (1024 * 1024):.2f} MB...")

                        for chunk in response.iter_content(
                            chunk_size=1024 * 1024
                        ):  # 1MB chunks
                            if chunk:
                                f.write(chunk)
                                downloaded_size += len(chunk)

                                # Show progress on each chunk
                                if total_size > 0:
                                    progress_mb = downloaded_size / (1024 * 1024)
                                    total_mb = total_size / (1024 * 1024)
                                    percentage = (downloaded_size / total_size) * 100
                                    print(
                                        f"Downloaded {progress_mb:.2f} MB of {total_mb:.2f} MB ({percentage:.1f}%)",
                                        end="\r",
                                    )

                    # Add newline after download completes
                    if total_size > 0:
                        print()

                    # Verify the downloaded file with size check
                    expected_size = total_size if total_size > 0 else None
                    if verify_vsix(temp_path, expected_size):
                        # Calculate and display file hash for verification
                        file_hash = calculate_sha256(temp_path)
                        if file_hash:
                            print(f"File SHA-256: {file_hash}")

                        # Move the temporary file to the final location
                        os.replace(temp_path, output_path)
                        print(f"Success! Downloaded to: {output_path}")
                        return True
                    else:
                        # Remove the invalid file
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                        print("Download completed but file verification failed.")
                        if attempt < max_attempts:
                            print(f"Retrying download in {attempt} seconds...")
                            time.sleep(attempt)
                        continue
                else:
                    print(f"Download failed with status code: {response.status_code}")
                    if response.text:
                        print(
                            f"Response: {response.text[:200]}..."
                        )  # Print first 200 chars of response
                    if attempt < max_attempts:
                        print(f"Retrying download in {attempt} seconds...")
                        time.sleep(attempt)
                    continue

            except requests.exceptions.RequestException as e:
                print(f"Download error: {e}")
                # Clean up partial download if it exists
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                if attempt < max_attempts:
                    print(f"Retrying download in {attempt} seconds...")
                    time.sleep(attempt)
                continue

        print("All download attempts failed.")
        return False

    # Download universal package only
    print(
        f"Attempting to download {publisher}.{extension}{' version ' + version if version else ''}..."
    )

    if download_file_with_retry(base_url, filepath):
        return True

    # If we get here, download failed
    print(
        "Error: Failed to download extension. Please check the extension ID and version."
    )
    print("You might want to try downloading manually from the marketplace.")
    return False


def main():
    args = parse_args()

    # Check for updates
    check_for_updates()

    publisher, extension = parse_extension_id(args.extension_id)

    if not publisher or not extension:
        print("Error: Could not parse publisher and extension from input")
        print(f"Input was: {args.extension_id}")
        print("Please use format 'publisher.extension' or a marketplace URL")
        sys.exit(1)

    # Handle version specification
    version = args.version
    if args.latest:
        # --latest flag overrides any version specification
        version = None
    elif not version and sys.stdin.isatty():
        # Only prompt if not using --latest flag and in interactive mode
        version = input("Enter version (leave blank for latest): ")

    success = download_extension(publisher, extension, version, args.directory)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
