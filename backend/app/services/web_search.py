import httpx
from html.parser import HTMLParser
import logging

logger = logging.getLogger(__name__)

class DDGParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self.current_result = {}
        self.in_snippet = False
        self.in_title = False
        self.temp_title = []
        self.temp_snippet = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        class_name = attrs_dict.get("class", "")
        
        if tag == "div" and "result" in class_name.split():
            self.current_result = {}
            
        elif tag == "a" and "result__snippet" in class_name.split():
            self.in_snippet = True
            self.temp_snippet = []
            if "href" in attrs_dict:
                self.current_result["url"] = attrs_dict["href"]
                
        elif tag == "a" and "result__url" in class_name.split():
            self.in_title = True
            self.temp_title = []
            if "href" in attrs_dict:
                self.current_result["url"] = attrs_dict["href"]

    def handle_endtag(self, tag):
        if tag == "a" and self.in_snippet:
            self.in_snippet = False
            self.current_result["snippet"] = "".join(self.temp_snippet).strip()
            if self.current_result.get("url") and self.current_result.get("snippet"):
                self.results.append(self.current_result.copy())
                self.current_result = {}
        elif tag == "a" and self.in_title:
            self.in_title = False
            self.current_result["title"] = "".join(self.temp_title).strip()

    def handle_data(self, data):
        if self.in_snippet:
            self.temp_snippet.append(data)
        elif self.in_title:
            self.temp_title.append(data)

async def perform_web_search(query: str) -> list[dict]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    # Properly encode query parameters using httpx
    params = httpx.QueryParams(q=query)
    url = f"https://html.duckduckgo.com/html/?{params}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            if response.status_code != 200:
                logger.error(f"DuckDuckGo search failed with status code {response.status_code}")
                return []
            
            parser = DDGParser()
            parser.feed(response.text)
            return parser.results
    except Exception as e:
        logger.exception("Error performing web search")
        return []
