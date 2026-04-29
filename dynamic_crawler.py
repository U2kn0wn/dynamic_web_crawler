import asyncio
import argparse
import json
import csv
import re
import os
from urllib.parse import urljoin, urlparse, urlunparse
from typing import Set
from playwright.async_api import async_playwright, Request, Response, Route

# Regex to find paths and URLs in JSON strings or JS code
# This captures: /api/v1/..., http://..., and relative ./path/...
URL_REGEX = r"""(?:"|')((?:/|https?://|[\w\d\-_.]+/)[\w\d./?%&=-]+)(?:"|')"""

class ReconLogger:
    def __init__(self, output_base: str):
        self.output_json = f"{output_base}.json"
        self.output_csv = f"{output_base}.csv"
        self.results = []

    def log_discovery(self, entry: dict):
        # Prevent duplicate logs for the same URL in the same session
        if not any(d['url'] == entry['url'] and d['method'] == entry['method'] for d in self.results):
            self.results.append(entry)
            print(f"[*] [{entry['method']}] {entry['status']} - {entry['url']} ({entry['source']})")

    def export(self):
        with open(self.output_json, 'w') as f:
            json.dump(self.results, f, indent=4)
        if self.results:
            keys = self.results[0].keys()
            with open(self.output_csv, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(self.results)
        print(f"\n[+] Total Discovered: {len(self.results)}")
        print(f"[+] Results saved to {self.output_json} and {self.output_csv}")

class ValkyrieCrawler:
    def __init__(self, start_url: str, max_depth: int, concurrency: int, headers: dict, output: str):
        self.start_url = start_url
        self.base_domain = urlparse(start_url).netloc
        self.max_depth = max_depth
        self.concurrency_limit = asyncio.Semaphore(concurrency)
        self.headers = headers
        self.logger = ReconLogger(output)
        self.visited_urls: Set[str] = set()
        self.queue = asyncio.Queue()

    def normalize_url(self, url: str) -> str:
        parsed = urlparse(url)
        query = "&".join(sorted(parsed.query.split("&"))) if parsed.query else ""
        normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, ""))
        return normalized.rstrip('/')

    def is_in_scope(self, url: str) -> bool:
        return urlparse(url).netloc == self.base_domain

    async def extract_from_text(self, text: str, source_url: str) -> Set[str]:
        found = set()
        matches = re.findall(URL_REGEX, text)
        for m in matches:
            # Basic cleanup for common false positives in JS/JSON
            if m.startswith(('n/a', 'undefined', 'null')) or len(m) < 2:
                continue
            full_url = urljoin(source_url, m)
            if self.is_in_scope(full_url):
                found.add(full_url)
        return found

    async def handle_request_interception(self, route: Route, request: Request):
        overrides = {**request.headers, **self.headers}
        await route.continue_(headers=overrides)

    async def on_response_handler(self, response: Response, current_depth: int, parent_url: str):
        """Processes EVERY network response for hidden URLs in the body."""
        try:
            content_type = response.headers.get("content-type", "").lower()
            url = response.url
            
            # 1. Log the network event
            self.logger.log_discovery({
                "url": url,
                "method": response.request.method,
                "status": response.status,
                "type": content_type,
                "source": "network_intercept",
                "depth": current_depth,
                "parent": parent_url
            })

            # 2. If it's JSON, JS, or Text, scan the body
            relevant_types = ['json', 'javascript', 'text/plain', 'text/html']
            if any(t in content_type for t in relevant_types) and response.status == 200:
                body = await response.text()
                discovered_links = await self.extract_from_text(body, url)
                
                for link in discovered_links:
                    norm = self.normalize_url(link)
                    if norm not in self.visited_urls:
                        # Add to queue with incremented depth
                        await self.queue.put((norm, current_depth + 1))
        except Exception:
            pass # Ignore failures for streaming or binary data

    async def process_page(self, url: str, depth: int, browser_context):
        if depth > self.max_depth or url in self.visited_urls:
            return
        
        self.visited_urls.add(url)
        page = await browser_context.new_page()

        # Attach response listener for this specific page instance
        page.on("response", lambda res: self.on_response_handler(res, depth, url))

        try:
            print(f"[>] Navigating to: {url}")
            response = await page.goto(url, wait_until="networkidle", timeout=60000)
            
            if response and response.status == 401:
                print(f"[!] AUTH EXPIRED (401) at {url}. Manual intervention required.")
            
            # Final scan of the fully rendered DOM
            content = await page.content()
            dom_links = await self.extract_from_text(content, url)
            for link in dom_links:
                norm = self.normalize_url(link)
                if norm not in self.visited_urls:
                    await self.queue.put((norm, depth + 1))

        except Exception as e:
            print(f"[-] Navigation Error [{url}]: {str(e)[:50]}")
        finally:
            await page.close()

    async def worker(self, browser_context):
        while True:
            url, depth = await self.queue.get()
            async with self.concurrency_limit:
                await self.process_page(url, depth, browser_context)
            self.queue.task_done()

    async def run(self):
        async with async_playwright() as p:
            # Use --no-sandbox for Linux environments
            browser = await p.chromium.launch(
                headless=True,
                executable_path="/usr/bin/chromium", # Points to Kali's native Chromium
                args=["--no-sandbox"]
                )
            context = await browser.new_context(user_agent="Valkyrie-VAPT-Scanner/2.0")
            
            # Apply headers globally to all requests
            await context.route("**/*", self.handle_request_interception)

            await self.queue.put((self.normalize_url(self.start_url), 0))
            
            workers = [asyncio.create_task(self.worker(context)) for _ in range(5)]
            await self.queue.join()
            
            for w in workers:
                w.cancel()
            await browser.close()
            self.logger.export()

def parse_raw_headers(header_string: str) -> dict:
    headers = {}
    if not header_string: return headers
    for line in header_string.strip().split('\n'):
        if ':' in line:
            key, value = line.split(':', 1)
            headers[key.strip()] = value.strip()
    return headers

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Valkyrie V2: JSON & Dynamic Crawler")
    parser.add_argument("-u", "--url", required=True)
    parser.add_argument("-d", "--depth", type=int, default=2)
    parser.add_argument("-c", "--concurrency", type=int, default=3)
    parser.add_argument("-o", "--output", default="vapt_results")
    parser.add_argument("-H", "--headers", help="Raw headers string")

    args = parser.parse_args()
    h_dict = parse_raw_headers(args.headers)
    
    crawler = ValkyrieCrawler(args.url, args.depth, args.concurrency, h_dict, args.output)
    asyncio.run(crawler.run())