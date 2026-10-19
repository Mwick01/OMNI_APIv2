#!/usr/bin/env python3
from scraper import scrape_and_download
from whatsapp_sender import send_notices

if __name__ == "__main__":
    print("=" * 50)
    print(f"🤖 RUH Notice Bot — {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    scrape_and_download()
    send_notices()
    print("\n✅ Done.")
