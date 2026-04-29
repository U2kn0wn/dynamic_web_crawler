import os
import re
import csv
import time
import threading
import argparse
from queue import Queue, Empty
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

class ReconCrawler:
    def __init__(self, start_url, raw_headers, max_depth=3):
        self.start_url = start_url
        self.domain = urlparse(start_url).netloc
        self.max_depth = max_depth
        
        # Shared State
        self.queue = Queue()
        self.visited = set()
        self.visited_lock = threading.Lock()
        self.results = []
        self.results_lock = threading.Lock()
        
        # Auth & Control
        self.session = requests.Session()
        self.headers = self.parse_headers(raw_headers)
        self.pause_event = threading.Event()
        self.pause_event.set() # Set means "Running"
        self.auth_lock = threading.Lock()

        # Initialization
        self.queue.put((start_url, "manual", 0, None))

    def parse_headers(self, raw_text):
        headers = {}
        lines = raw_text.strip().split('\n')
        for line in lines:
            if ':' in line:
                key, value = line.split(':', 1)
                k = key.strip()
                if k.lower() not in ['host']: # Ignore Host header
                    headers[k] = value.strip()
        return headers

    def update_headers_ui(self):
        if self.auth_lock.acquire(blocking=False):
            self.pause_event.clear()
            print("\n[!] AUTHENTICATION EXPIRED (401 Unauthorized)")
            print("[?] Please paste new raw headers (End with Ctrl+D or an empty line):")
            
            new_lines = []
            while True:
                try:
                    line = input()
                    if not line: break
                    new_lines.append(line)
                except EOFError: break
            
            new_raw = "\n".join(new_lines)
            if new_raw.strip():
                self.headers = self.parse_headers(new_raw)
                print("[+] Headers updated. Resuming...")
            
            self.pause_event.set()
            self.auth_lock.release()
        else:
            # If another thread is already handling the update, just wait
            self.pause_event.wait()

    def extract_endpoints(self, html_content, base_url):
        found = []
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 1. HTML Attributes
        tags = {'a': 'href', 'script': 'src', 'form': 'action', 'img': 'src', 'link': 'href'}
        for tag, attr in tags.items():
            for element in soup.find_all(tag, **{attr: True}):
                found.append((element[attr], f"html_{tag}"))

        # 2. Regex for JS/Text patterns (relative paths & full URLs)
        # Matches patterns like "/api/v1/user" or "https://domain.com/endpoint"
        js_patterns = [
            r'[\'"](/[a-zA-Z0-9\._\-/]+)[\'"]', # Relative paths in strings
            r'(https?://[^\s\'"<>]+)'           # Absolute URLs
        ]
        for pattern in js_patterns:
            matches = re.findall(pattern, html_content)
            for m in matches:
                found.append((m, "regex_js"))

        # Normalize and filter
        normalized = []
        for link, src_type in found:
            full_url = urljoin(base_url, link)
            if urlparse(full_url).netloc == self.domain:
                normalized.append((full_url, src_type))
        
        return list(set(normalized))

    def worker(self):
        while not self.queue.empty() or self.pause_event.is_set():
            self.pause_event.wait() # Global pause if 401 occurs
            
            try:
                url, src_type, depth, parent = self.queue.get(timeout=3)
            except Empty:
                break

            with self.visited_lock:
                if url in self.visited:
                    self.queue.task_done()
                    continue
                self.visited.add(url)

            try:
                start_time = time.time()
                resp = self.session.get(url, headers=self.headers, timeout=10, allow_redirects=True)
                elapsed = time.time() - start_time

                if resp.status_code == 401:
                    self.queue.put((url, src_type, depth, parent)) # Re-queue
                    self.update_headers_ui()
                    self.queue.task_done()
                    continue

                # Log metadata
                metadata = {
                    "URL": url,
                    "Status": resp.status_code,
                    "Parent": parent,
                    "Depth": depth,
                    "Type": resp.headers.get('Content-Type', 'unknown').split(';')[0],
                    "Time": f"{elapsed:.3f}s",
                    "Source": src_type
                }
                with self.results_lock:
                    self.results.append(metadata)
                
                print(f"[{resp.status_code}] {url}")

                # Crawl further
                if depth < self.max_depth and "text/html" in resp.headers.get('Content-Type', ''):
                    new_endpoints = self.extract_endpoints(resp.text, url)
                    for link, link_type in new_endpoints:
                        self.queue.put((link, link_type, depth + 1, url))

            except Exception as e:
                print(f"[!] Error accessing {url}: {e}")
            
            self.queue.task_done()

    def run(self):
        threads = []
        for _ in range(5): # MANDATORY: Exactly 5 threads
            t = threading.Thread(target=self.worker)
            t.start()
            threads.append(t)

        for t in threads:
            t.join()
        
        self.export_csv()

    def export_csv(self):
        filename = f"{self.domain.replace('.', '_')}_crawl.csv"
        keys = ["URL", "Status", "Parent", "Depth", "Type", "Time", "Source"]
        with open(filename, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(self.results)
        print(f"\n[+] Scan Complete. Results saved to: {filename}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lightweight Recon Crawler")
    parser.add_argument("-u", "--url", required=True, help="Starting URL")
    parser.add_argument("-d", "--depth", type=int, default=3, help="Max crawl depth")
    args = parser.parse_args()

    print("[?] Paste raw HTTP headers (Empty line + Enter to finish):")
    headers_input = []
    while True:
        line = input()
        if not line: break
        headers_input.append(line)
    
    crawler = ReconCrawler(args.url, "\n".join(headers_input), args.depth)
    crawler.run()
