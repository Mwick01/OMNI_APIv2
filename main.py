#!/usr/bin/env python3
import subprocess
import sys
from scraper import scrape_and_download

def run_whatsapp_sender():
    print("\n📲 Starting WhatsApp sender...")
    result = subprocess.run(["node", "whatsapp_sender.js"])
    if result.returncode != 0:
        print(f"❌ WhatsApp sender failed (exit {result.returncode})")
        sys.exit(result.returncode)

if __name__ == "__main__":
    print("=" * 50)
    print("🤖 RUH Notice Bot (whatsapp-web.js)")
    print("=" * 50)
    scrape_and_download()
    run_whatsapp_sender()
    print("\n✅ Done.")
