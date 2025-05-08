#!/usr/bin/env python3

import argparse
import os
import re
import socket
import sys
import time
from urllib.parse import urlparse, parse_qs
import requests

# Default timeout for HTTP requests (in seconds)
DEFAULT_TIMEOUT = 10
# Number of retries for HTTP requests
MAX_RETRIES = 3


def check_network_connectivity(host="marketplace.visualstudio.com", port=443, timeout=5):
    """Check if we can connect to the specified host and port."""
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except socket.error as ex:
        print(f"Network connectivity check failed: {ex}")
        return False


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download VS Code extensions from the Visual Studio Marketplace",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s ms-python.python
  %(prog)s -v 2023.4.1 ms-python.python
  %(prog)s -d ~/Downloads https://marketplace.visualstudio.com/items?itemName=ms-python.python
  %(prog)s --skip-version-check ms-python.python
  %(prog)s --proxy http://proxy.example.com:8080 ms-python.python
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

    parser.add_argument(
        "--skip-version-check",
        action="store_true",
        help="Skip checking for the latest version and download directly"
    )

    parser.add_argument(
        "-t", "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Timeout in seconds for HTTP requests (default: {DEFAULT_TIMEOUT})"
    )

    parser.add_argument(
        "--proxy",
        help="HTTP proxy to use (e.g., http://proxy.example.com:8080)"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode with more verbose output"
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


def download_extension(publisher, extension, version, directory, skip_version_check=False):
    """Download the extension from the marketplace."""
    # Create directory if it doesn't exist
    os.makedirs(directory, exist_ok=True)

    # Get version information and construct base URL
    if not version:
        print("No version specified, fetching latest...")
        actual_version = "latest"

        if not skip_version_check:
            for attempt in range(MAX_RETRIES):
                response = None
                try:
                    # Try to get the latest version information with timeout
                    api_url = f"https://marketplace.visualstudio.com/_apis/public/gallery/publishers/{publisher}/vsextensions/{extension}"
                    print(f"Fetching version info from: {api_url}")
                    print(f"Attempt {attempt + 1}/{MAX_RETRIES}...")

                    response = requests.get(api_url, timeout=DEFAULT_TIMEOUT)
                    print(f"Response status code: {response.status_code}")

                    if response.status_code == 200:
                        data = response.json()
                        if 'versions' in data and len(data['versions']) > 0:
                            actual_version = data['versions'][0]['version']
                            print(f"Latest version: {actual_version}")
                            version = actual_version
                            break
                        else:
                            print("Could not determine latest version from response data")
                    else:
                        print(f"Could not fetch version information: HTTP {response.status_code}")
                        if response.status_code != 404:  # Only show response text for non-404 errors
                            print(f"Response: {response.text[:200]}...")

                        # Don't retry on 404 errors
                        if response.status_code == 404:
                            print("Extension not found (404). Check the publisher and extension name.")
                            break

                except requests.exceptions.Timeout:
                    print(f"Request timed out after {DEFAULT_TIMEOUT} seconds")
                except requests.exceptions.ConnectionError as e:
                    print(f"Connection error: {e}")
                except Exception as e:
                    print(f"Error fetching version information: {e}")

                # Wait before retrying (exponential backoff)
                if attempt < MAX_RETRIES - 1:
                    retry_delay = 2 ** attempt
                    print(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)

            if actual_version == "latest":
                print("Could not determine version after all attempts, using 'latest' in filename")

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

        for attempt in range(MAX_RETRIES):
            try:
                print(f"Download attempt {attempt + 1}/{MAX_RETRIES}...")

                # Download the file with timeout
                response = requests.get(url, stream=True, timeout=DEFAULT_TIMEOUT)
                print(f"Response status code: {response.status_code}")

                # Check if the request was successful
                if response.status_code == 200:
                    # Get the total file size if available
                    total_size = int(response.headers.get('content-length', 0))

                    # Download with progress indication
                    with open(temp_path, 'wb') as f:
                        if total_size > 0:
                            print(f"Downloading {total_size / (1024 * 1024):.2f} MB...")
                        else:
                            print("Downloading file (size unknown)...")

                        downloaded = 0
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if total_size > 0 and downloaded % (1024 * 1024) < 8192:  # Show progress every ~1MB
                                    print(f"Downloaded {downloaded / (1024 * 1024):.2f} MB of {total_size / (1024 * 1024):.2f} MB ({downloaded / total_size * 100:.1f}%)")

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
                        # Don't retry if verification failed - likely a server issue
                        return False
                else:
                    print(f"Download failed with status code: {response.status_code}")
                    if response.status_code != 404:  # Only show response text for non-404 errors
                        print(f"Response: {response.text[:200]}...")  # Print first 200 chars of response

                    # Don't retry on 404 errors
                    if response.status_code == 404:
                        print("Resource not found (404). Check the extension ID and version.")
                        return False
            except requests.exceptions.Timeout:
                print(f"Download request timed out after {DEFAULT_TIMEOUT} seconds")
            except requests.exceptions.ConnectionError as e:
                print(f"Connection error during download: {e}")
            except Exception as e:
                print(f"Download error: {e}")

            # Clean up partial download if it exists
            if os.path.exists(temp_path):
                os.remove(temp_path)

            # Wait before retrying (exponential backoff)
            if attempt < MAX_RETRIES - 1:
                retry_delay = 2 ** attempt
                print(f"Retrying download in {retry_delay} seconds...")
                time.sleep(retry_delay)

        print("All download attempts failed.")
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

    # Update global timeout if specified
    global DEFAULT_TIMEOUT
    if args.timeout != DEFAULT_TIMEOUT:
        DEFAULT_TIMEOUT = args.timeout
        print(f"Using custom timeout: {DEFAULT_TIMEOUT} seconds")

    # Configure proxy if specified
    if args.proxy:
        print(f"Using proxy: {args.proxy}")
        os.environ['HTTP_PROXY'] = args.proxy
        os.environ['HTTPS_PROXY'] = args.proxy

    # Enable debug mode if requested
    if args.debug:
        print("Debug mode enabled")
        # You could set up more verbose logging here if needed
        import http.client as http_client
        http_client.HTTPConnection.debuglevel = 1

        # Enable requests logging
        import logging
        logging.basicConfig()
        logging.getLogger().setLevel(logging.DEBUG)
        requests_log = logging.getLogger("requests.packages.urllib3")
        requests_log.setLevel(logging.DEBUG)
        requests_log.propagate = True

    # Check network connectivity first
    print("Checking network connectivity...")
    if not check_network_connectivity():
        print("WARNING: Cannot connect to marketplace.visualstudio.com")
        print("This may indicate network issues or proxy configuration problems.")
        print("The script will continue but may fail to download.")
        print("Try using a higher timeout value with -t/--timeout option.")
        if not args.proxy:
            print("If you're behind a proxy, use the --proxy option.")
        print()

    publisher, extension = parse_extension_id(args.extension_id)

    if not publisher or not extension:
        print("Error: Could not parse publisher and extension from input")
        print(f"Input was: {args.extension_id}")
        print("Please use format 'publisher.extension' or a marketplace URL")
        sys.exit(1)

    # If version is not provided and we're in interactive mode, prompt for it
    version = args.version
    if not version and sys.stdin.isatty() and not args.skip_version_check:
        version = input("Enter version (leave blank for latest): ")

    if args.skip_version_check:
        print("Skipping version check as requested")

    success = download_extension(
        publisher,
        extension,
        version,
        args.directory,
        skip_version_check=args.skip_version_check
    )

    if not success:
        print("\nTROUBLESHOOTING TIPS:")
        print("1. Try using the --skip-version-check option to bypass version lookup")
        print("2. Try increasing the timeout with -t/--timeout (e.g., -t 30)")
        print("3. Check your network connection and proxy settings")
        print("4. If you're behind a corporate firewall, use --proxy http://your-proxy:port")
        print("5. Use --debug to get more detailed error information")
        print("\nExample with all troubleshooting options:")
        print(f"  {sys.argv[0]} --skip-version-check --timeout 30 --proxy http://your-proxy:port {args.extension_id}")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
