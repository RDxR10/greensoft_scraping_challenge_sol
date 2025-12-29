import os
import re
import shutil
from playwright.sync_api import sync_playwright
from urllib.parse import urljoin, urlparse
import time
from lxml import etree


BASE_URL = "https://revistas.udca.edu.co"
ARTICLE_URL = "https://revistas.udca.edu.co/index.php/ruadc/article/view/{}"
ROOT = "936719013"
JOURNAL = "Revista U.D.C.A Actualidad & Divulgación Científica"
article_id = 2373

os.makedirs(ROOT, exist_ok=True)
folder = os.path.join(ROOT, str(article_id))
os.makedirs(folder, exist_ok=True)



def playwright_scrape():
    max_retries = 3

    for attempt in range(max_retries):
        print(f" Attempt {attempt + 1}/{max_retries}")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                slow_mo=100,
                args=[
                    '--no-sandbox',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor'
                ]
            )

            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                extra_http_headers={
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9,es;q=0.8',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1',
                    'Upgrade-Insecure-Requests': '1',
                },
            )

            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                window.chrome = { runtime: {} };
            """)

            page = context.new_page()
            page.set_extra_http_headers({'Referer': BASE_URL})

            try:
                print(" Pre-warming base domain...")
                page.goto(BASE_URL, wait_until='domcontentloaded', timeout=15000)
                page.wait_for_timeout(2000)

                print(f" Loading article...")
                response = page.goto(
                    ARTICLE_URL.format(article_id),
                    wait_until='domcontentloaded',
                    timeout=45000
                )

                if not response or response.status != 200:
                    raise Exception(f"HTTP {response.status if response else 'No response'}")

                page.wait_for_timeout(5000)
                try:
                    page.wait_for_selector('h1, .page_title, title', timeout=10000)
                except:
                    pass

                page.wait_for_timeout(3000)


                data = extract_metadata(page)
                if not data:
                    print("Metadata extraction failed")
                    continue

                print(f" Title: {data['title']}")
                print(f" Year: {data['year']}")
                print(f" Volume: {data['volume']}")
                print(f" Issue: {data['issue']}")
                print(f" DOI: {data['doi']}")
                print(f" Authors: {len(data['authors'])} found")


                if data["galley_url"]:
                    pdf_name, pdf_size = download_pdf_playwright(page, data["galley_url"], folder)
                    data["pdf_name"] = pdf_name
                    data["pdf_size"] = pdf_size
                else:
                    data["pdf_name"] = ""
                    data["pdf_size"] = 0

                write_xml(data, folder, pdf_name, pdf_size)
                print(" SUCCESS! Full metadata extracted.")
                return

            except Exception as e:
                print(f" Attempt {attempt+1} failed: {str(e)[:100]}...")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)

            finally:
                browser.close()
                time.sleep(1)

def extract_metadata(page):
    try:
        print("Extracting full metadata...")


        title_selectors = [
            'h1.page_title', 'h1.title', '.page_title h1',
            'h1', '.article-title', '#articleTitle'
        ]
        title = ""
        for sel in title_selectors:
            try:
                elem = page.query_selector(sel)
                if elem:
                    title = elem.inner_text().strip()
                    break
            except:
                continue

        if not title:
            title = page.title().strip()

        print(f"    Title: {title[:80]}{'...' if len(title) > 80 else ''}")


        meta = {}
        meta_selectors = {
            "DC.Identifier.DOI": 'meta[name="DC.Identifier.DOI"]',
            "DC.Date": 'meta[name="DC.Date"]',
            "DC.Date.issued": 'meta[name="DC.Date.issued"]',
            "DC.Subject": 'meta[name="DC.Subject"]',
            "DC.Source.Volume": 'meta[name="DC.Source.Volume"]',      
            "DC.Source.Issue": 'meta[name="DC.Source.Issue"]'
        }

        for key, selector in meta_selectors.items():
            try:
                element = page.query_selector(f'meta[name="{key}"]')
                if element:
                    meta[key] = element.get_attribute('content') or ""
            except:
                continue


        volume = meta.get("DC.Source.Volume") or meta.get("citation_volume", "").strip()
        print(f"Volume: {volume}")


        issue = meta.get("DC.Source.Issue") or meta.get("citation_issue", "").strip()
        print(f"Issue: {issue}")


        year_candidates = []
        if meta.get("DC.Date"):
            year_candidates.append(meta["DC.Date"][:4])
        if meta.get("DC.Date.issued"):
            year_candidates.append(meta["DC.Date.issued"][:4])

        year = ""
        for y in year_candidates:
            if re.match(r'^\d{4}$', y) and 1900 <= int(y) <= 2026:
                year = y
                break


        doi = meta.get("DC.Identifier.DOI", "").strip()


        keywords = meta.get("DC.Subject", "")
        if not keywords:
            selectors = ["div.keyword-item a", ".keywords a", "div.keywords a"]
            for sel in selectors:
                elements = page.query_selector_all(sel)
                if elements:
                    keywords = "|||||||".join(el.inner_text().strip() for el in elements)
                    break
        keywords = keywords.replace(", ", "|||||||").strip()


        authors = []
        author_selectors = ["div.authors div.author", ".author", "div.author"]
        auth_divs = []

        for sel in author_selectors:
            auth_divs = page.query_selector_all(sel)
            if auth_divs:
                break

        affil_selectors = ["div.article-author-affilitation", ".affiliation", "div.affiliation"]
        affils = []
        for sel in affil_selectors:
            affils = page.query_selector_all(sel)
            if affils:
                break

        for i, div in enumerate(auth_divs[:10]):
            try:
                strong = div.query_selector("strong, .name, h4")
                if not strong:
                    continue
                name = strong.inner_text().strip()
                orcid_tag = div.query_selector('a[href*="orcid.org"]')
                orcid = orcid_tag.get_attribute('href') if orcid_tag else ""
                affil = affils[i].inner_text().strip() if i < len(affils) else ""
                authors.append((name, affil, orcid))
            except:
                continue

        
        galley_selectors = [
            'a.galley-link.obj_galley_link.pdf',
            'a[href*=".pdf"]',
            '.galley-link[href$=".pdf"]',
            'a.download'
        ]
        galley_url = ""
        for sel in galley_selectors:
            galley = page.query_selector(sel)
            if galley:
                href = galley.get_attribute('href')
                if href:
                    galley_url = urljoin(BASE_URL, href)
                    break

        return {
            "title": title,
            "authors": authors,
            "keywords": keywords,
            "year": year,
            "volume": volume,    
            "issue": issue,      
            "job_id": str(article_id),
            "doi": doi,
            "galley_url": galley_url,
        }

    except Exception as e:
        print(f"Metadata error: {e}")
        return None

def download_pdf_playwright(page, galley_url, folder):
    try:
        page.goto(galley_url, wait_until='domcontentloaded', timeout=30000)
        page.wait_for_timeout(3000)

        dl_selectors = ["a.download", 'a[href$=".pdf"]', ".download"]
        dl_link = None
        for sel in dl_selectors:
            dl_link = page.query_selector(sel)
            if dl_link:
                break

        if not dl_link:
            return "", 0

        pdf_url = dl_link.get_attribute('href')
        if not pdf_url.startswith('http'):
            pdf_url = urljoin(BASE_URL, pdf_url)

        with page.expect_download(timeout=45000) as download_info:
            dl_link.click(force=True)

        download = download_info.value
        filename = os.path.basename(urlparse(pdf_url).path) or f"{article_id}.pdf"
        if not filename.endswith('.pdf'):
            filename += '.pdf'

        path = os.path.join(folder, filename)
        download.save_as(path)
        size = os.path.getsize(path)
        print(f" PDF saved: {filename} ({size:,} bytes)")
        return filename, size

    except Exception as e:
        print(f"PDF download failed: {e}")
        return "", 0


	
def escape_(text):
    return re.sub(r'&(?!#?\w+;)', '&amp;', text)

def write_xml(data, folder, pdf_name="", pdf_size=0):
    authors_xml = ""
    for n, a, o in data.get("authors", []):
        authors_xml += f"""        <Author>
            <Name>{n}</Name>
            <Affiliation>{a}</Affiliation>
            <ORCID>{o}</ORCID>
        </Author>"""

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Article>
    <Title>{data.get('title', '')}</Title>
    <Authors>
{authors_xml}
    </Authors>
    <Keywords>{data.get('keywords', '')}</Keywords>
    <PDFName>{pdf_name}</PDFName>
    <FileSize>{pdf_size}</FileSize>
    <PublicationYear>{data.get('year', '')}</PublicationYear>
    <Volume>{data.get('volume', '')}</Volume>
    <Issue>{data.get('issue', '')}</Issue>
    <SourceID>{data['job_id']}</SourceID>
    <ContentProvider>{JOURNAL}</ContentProvider>
    <DOI>{data.get('doi', '')}</DOI>
    <PublisherItemType>Journal Article</PublisherItemType>
    <StartPage/>
    <EndPage/>
    <PageRange/>
</Article>"""

    xml_path = os.path.join(folder, "metadata.xml")
    try:
        xml_content = escape_(xml)
        with open(xml_path, "w", encoding="utf-8") as f:            
            f.write(xml_content)       

        try:
            parser = etree.XMLParser(recover=False)
            etree.fromstring(xml_content.encode('utf-8'), parser=parser)
            print(f"Valid XML generated for article {data.get('job_id', 'unknown')}")
        except etree.XMLSyntaxError as e:
            print(f"XML validation warning for article {data.get('job_id', 'unknown')}: {e}")

            
    except Exception as e:
        print(f"[ERROR] Failed to write XML file: {e}")
        return False	
		
    return xml_path



if __name__ == "__main__":
    print("Running...")
    playwright_scrape()
