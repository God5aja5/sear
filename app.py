from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
from urllib.parse import urljoin, urlparse

app = Flask(__name__)

def brave_search(query):
    """Search using Brave Search API with no result limit"""
    headers = {
        'authority': 'search.brave.com',
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'accept-language': 'en-US,en;q=0.9',
        'cache-control': 'no-cache',
        'pragma': 'no-cache',
        'referer': 'https://search.brave.com/?lang=en-in',
        'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
        'sec-ch-ua-mobile': '?1',
        'sec-ch-ua-platform': '"Android"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'same-origin',
        'sec-fetch-user': '?1',
        'upgrade-insecure-requests': '1',
        'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
    }
    
    params = {
        'q': query,
        'source': 'web',
        'lang': 'en-in',
    }
    
    try:
        response = requests.get('https://search.brave.com/search', params=params, headers=headers, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            results = []
            seen_urls = set()
            
            # Comprehensive search result containers
            search_results = soup.find_all(['div', 'article', 'section'], class_=re.compile(r'result|search-result|web-result|card|snippet|item'))
            
            for result in search_results:
                # Try multiple link selectors
                link_elem = result.find('a', href=True) or result.find('a', class_=re.compile(r'title|link|url'))
                if link_elem:
                    url = link_elem.get('href')
                    if url:
                        # Clean and validate URL
                        url = urljoin('https://search.brave.com', url)
                        if (url.startswith('http') and 
                            'brave.com' not in url and 
                            url not in seen_urls and 
                            not any(ext in url.lower() for ext in ['.pdf', '.jpg', '.png', '.gif', '.jpeg'])):
                            
                            # Extract title from multiple possible elements
                            title_elem = (link_elem.find(['h2', 'h3', 'span', 'div'], class_=re.compile(r'title|heading')) or 
                                        link_elem)
                            title = title_elem.get_text(strip=True) if title_elem else link_elem.get_text(strip=True)
                            
                            # Extract description from multiple possible elements
                            desc_elem = result.find(['p', 'div', 'span'], class_=re.compile(r'desc|snippet|summary|meta|description'))
                            description = desc_elem.get_text(strip=True) if desc_elem else ""
                            
                            if not title:
                                title = urlparse(url).netloc
                            
                            results.append({
                                'title': title[:150] + '...' if len(title) > 150 else title,
                                'url': url,
                                'description': description[:300] + '...' if len(description) > 300 else description,
                                'domain': urlparse(url).netloc
                            })
                            seen_urls.add(url)
            
            # Comprehensive fallback for all links
            links = soup.find_all('a', href=True)
            for link in links:
                url = urljoin('https://search.brave.com', link.get('href'))
                if (url.startswith('http') and 
                    'brave.com' not in url and 
                    url not in seen_urls and 
                    not any(ext in url.lower() for ext in ['.pdf', '.jpg', '.png', '.gif', '.jpeg'])):
                    title = link.get_text(strip=True)
                    if title and len(title) > 5:
                        results.append({
                            'title': title[:150] + '...' if len(title) > 150 else title,
                            'url': url,
                            'description': '',
                            'domain': urlparse(url).netloc
                        })
                        seen_urls.add(url)
            
            return results
    except Exception as e:
        print(f"Search error: {e}")
        return []

def get_screenshot(url):
    """Get screenshot using Pikwy API"""
    headers = {
        'authority': 'api.pikwy.com',
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9',
        'cache-control': 'no-cache',
        'origin': 'https://pikwy.com',
        'pragma': 'no-cache',
        'referer': 'https://pikwy.com/',
        'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
        'sec-ch-ua-mobile': '?1',
        'sec-ch-ua-platform': '"Android"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-site',
        'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
    }
    
    params = {
        'tkn': '125',
        'd': '3000',
        'u': url,
        'fs': '0',
        'w': '1280',
        'h': '1200',
        's': '100',
        'z': '100',
        'f': 'jpg',
        'rt': 'jweb',
    }
    
    try:
        response = requests.get('https://api.pikwy.com/', params=params, headers=headers, timeout=20)
        if response.status_code == 200:
            data = response.json()
            return data.get('iurl', '')
    except Exception as e:
        print(f"Screenshot error for {url}: {e}")
    return None

def process_result_with_screenshot(result):
    """Process a single result and add screenshot"""
    screenshot_url = get_screenshot(result['url'])
    result['screenshot'] = screenshot_url
    return result

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search')
def search():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'error': 'No query provided'})
    
    # Get search results
    results = brave_search(query)
    
    if not results:
        return jsonify({'results': [], 'query': query, 'total': 0})
    
    # Get screenshots in parallel
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_result = {executor.submit(process_result_with_screenshot, result): result for result in results}
        processed_results = []
        
        for future in as_completed(future_to_result):
            try:
                result = future.result()
                processed_results.append(result)
            except Exception as e:
                print(f"Error processing result: {e}")
                original_result = future_to_result[future]
                original_result['screenshot'] = None
                processed_results.append(original_result)
    
    # Sort results to maintain original order
    url_to_index = {result['url']: i for i, result in enumerate(results)}
    processed_results.sort(key=lambda x: url_to_index.get(x['url'], float('inf')))
    
    return jsonify({
        'results': processed_results,
        'query': query,
        'total': len(processed_results)
    })

if __name__ == '__main__':
    app.run(debug=True)