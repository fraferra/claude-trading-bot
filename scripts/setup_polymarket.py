#!/usr/bin/env python3
"""Generate Polymarket CLOB API credentials from your wallet private key.

Usage:
    .venv/bin/python scripts/setup_polymarket.py

You'll be prompted for your private key (starts with 0x).
The script will derive apiKey, secret, and passphrase, then
print the .env lines to add.
"""

import getpass
import sys


def main():
    print("=== Polymarket API Credential Setup ===\n")
    print("This derives your CLOB API credentials from your Polygon wallet private key.")
    print("Your key is NOT stored — only used to derive credentials.\n")

    pk = getpass.getpass("Enter your Polygon wallet private key (0x...): ").strip()

    if not pk.startswith("0x"):
        print("Error: Private key should start with 0x")
        sys.exit(1)

    try:
        from py_clob_client.client import ClobClient
    except ImportError:
        print("Error: py-clob-client not installed. Run: pip install py-clob-client")
        sys.exit(1)

    print("\nDeriving API credentials from Polymarket CLOB...")

    client = ClobClient(
        host="https://clob.polymarket.com",
        chain_id=137,
        key=pk,
    )

    try:
        creds = client.create_or_derive_api_creds()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    api_key = creds.api_key if hasattr(creds, "api_key") else creds.get("apiKey", "")
    secret = creds.api_secret if hasattr(creds, "api_secret") else creds.get("secret", "")
    passphrase = creds.api_passphrase if hasattr(creds, "api_passphrase") else creds.get("passphrase", "")

    print("\n=== Success! Add these to your .env file ===\n")
    print(f"POLYMARKET_PRIVATE_KEY={pk}")
    print(f"POLYMARKET_API_KEY={api_key}")
    print(f"POLYMARKET_API_SECRET={secret}")
    print(f"POLYMARKET_API_PASSPHRASE={passphrase}")
    print("\nAlso set polymarket.paper to false in config.yaml for live trading.")


if __name__ == "__main__":
    main()
