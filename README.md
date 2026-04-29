# Web Crawler & Playwright Scraper

This repository contains two Python scripts:

* `crawler.py` → A lightweight HTTP crawler using `requests` and `BeautifulSoup`
* `dynamic_crawler.py` → A browser-based scraper using `playwright`

Together, they allow you to fetch, parse, and interact with web pages using both static and dynamic approaches.

---

## Requirements

Install dependencies using:

```bash
pip install -r requirements.txt
```

### `requirements.txt`

```txt
playwright
requests
beautifulsoup4
```

After installing Playwright, run:

```bash
playwright install
```

---

## Project Structure

```
.
├── crawler.py      # HTTP-based crawler (fast, no JS execution)
├── dynamic_crawler.py        # Playwright-based scraper (handles dynamic sites)
├── requirements.txt
└── README.md
```

---

## Usage

### 1. Run the HTTP Crawler

```bash
python crawler.py
```

**What it does:**

* Sends HTTP requests to target URLs
* Parses HTML using BeautifulSoup
* Extracts relevant data (links, text, etc.)

**Best for:**

* Static websites
* Fast scraping
* Low resource usage

---

### 2. Run the Playwright Script

```bash
python dynamic_crawler.py
```

**What it does:**

* Launches a real browser (Chromium)
* Interacts with JavaScript-heavy websites
* Waits for dynamic content to load

**Best for:**

* Dynamic websites (React, Angular, etc.)
* Pages requiring interaction (clicks, scrolling)

---

## Configuration

### Chromium Path (Important)

Your script uses:

```
/usr/bin/chromium
```

Make sure Chromium is installed on your system:

```bash
sudo apt install chromium-browser
```

Or modify the path inside `dynamic_crawler.py` if needed.

---

## When to Use Which?

| Use Case                 | Recommended Script |
| ------------------------ | ------------------ |
| Static HTML scraping     | `crawler.py`       |
| JavaScript-rendered data | `dynamic_crawler.py`         |
| Login / interaction      | `dynamic_crawler.py`         |
| High-speed crawling      | `crawler.py`       |

---

## Notes

* Respect website **robots.txt** and terms of service
* Avoid sending too many requests in a short time
* Use delays if scraping at scale

---

## Possible Improvements

* Add logging
* Add CLI arguments (URLs, depth, etc.)
* Export data to CSV/JSON
* Add proxy support
* Handle retries and timeouts

---

## License

This project is for educational and personal use.

---

## Author

Your Name Here
