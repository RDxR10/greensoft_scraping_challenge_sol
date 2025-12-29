import os
import re
import shutil
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import urllib3
from urllib3.util import Timeout


from lxml import etree

ARTICLE_URL_TEMPLATE = "https://revistas.udca.edu.co/index.php/ruadc/article/view/{}"

JOB_ID = "936719006"
ROOT_FOLDER = JOB_ID
START_ID = 2000
END_ID = 3000
TARGET_YEARS = {"2024", "2025"}
HARDCODED_JOURNAL_NAME = "Revista U.D.C.A Actualidad & Divulgación Científica"

http = urllib3.PoolManager()
timeout = Timeout(connect=30.0, read=30.0)
os.makedirs(ROOT_FOLDER, exist_ok=True)

def get_soup(url):
    try:
        r = http.request('GET', url, timeout=timeout)
        if r.status != 200:
            return None
        return BeautifulSoup(r.data, 'lxml')
    except Exception as e:
        print(f"[ERROR] Couldn't load page {url}: {e}")
        return None

def download_file(href, base_url, folder_path):
    try:

        if "article/view/" in href:
            download_href = href.replace("view", "download", 1)
            pdf_url = urljoin(base_url, download_href)

            filename = os.path.basename(pdf_url) + ".pdf"  
            file_path = os.path.join(folder_path, filename)

            response = http.request('GET', pdf_url, preload_content=False, timeout=timeout)
            if response.status == 200:
                with open(file_path, 'wb') as out_file:
                    shutil.copyfileobj(response, out_file)
                size = os.path.getsize(file_path)
                response.release_conn()
                return filename, size
            else:
                print(f"[WARN] Direct PDF download failed: {pdf_url}")
                return None, 0
        else:
            print(f"[WARN] Unexpected href format: {href}")
    except Exception as e:
        print(f"[ERROR] Exception during direct PDF download: {e}")
    return None, 0



def sanitize(text):
    return re.sub(r'[\\/*?:"<>|]', "-", text.strip())[:100]

def is_valid_folder_name(name):
    return bool(re.match(r'^[\w\s\-.()]+$', name.strip()))

def escape_(text):

    return re.sub(r'&(?!#?\w+;)', '&amp;', text)

def generate_xml(metadata, files_info, folder_path):
    author_tags = ""
    for name, affil, orcid in metadata["authors"]:
        author_tags += f"""        <Author>
            <Name>{name}</Name>
            <Affiliation>{affil}</Affiliation>
            <ORCID>{orcid}</ORCID>
        </Author>\n"""

    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<Article>
    <Title>{metadata['title']}</Title>
    <Authors>{author_tags.strip()}</Authors>
    <Keywords>{metadata['keywords']}</Keywords>
    <PDFName>{files_info.get('pdf_name', '')}</PDFName>
    <FileSize>{files_info.get('pdf_size', 0)}</FileSize>
    <PublicationYear>{metadata['year']}</PublicationYear>
    <Volume>{metadata.get('volume', '')}</Volume>
    <Issue>{metadata.get('issue', '')}</Issue>
    <SourceID>{metadata['job_id']}</SourceID>
    <ContentProvider>{HARDCODED_JOURNAL_NAME}</ContentProvider>
    <DOI>{metadata['doi']}</DOI>
    <PublisherItemType>Journal Article</PublisherItemType>
    <StartPage></StartPage>
    <EndPage></EndPage>
    <PageRange></PageRange>
    <Abstract>{metadata['abstract']}</Abstract>
    <References>{metadata['references']}</References>
</Article>
"""
    xml_file_path = os.path.join(folder_path, "metadata.xml")
    
    try:
        xml_content = escape_(xml_content)
        with open(xml_file_path, "w", encoding="utf-8") as f:
            
            f.write(xml_content)
        

        try:

            parser = etree.XMLParser(recover=False)
            etree.fromstring(xml_content.encode('utf-8'), parser=parser)
            print(f"Valid XML generated for article {metadata.get('job_id', 'unknown')}")
        except etree.XMLSyntaxError as e:
            print(f"XML validation warning for article {metadata.get('job_id', 'unknown')}: {e}")

            
    except Exception as e:
        print(f"[ERROR] Failed to write XML file: {e}")
        return False

def extract_metadata(article_url, article_id):
    soup = get_soup(article_url)
    if not soup:
        return None


    title_tag = soup.select_one("span.text-to-voice-body") or soup.find("h1", class_="page-header")
    title = title_tag.text.strip() if title_tag else ""


    authors = []
    author_tags = soup.select("div.authors div.author")
    affil_tags = soup.select("div.article-author-affilitation")
    

    for i, div in enumerate(author_tags):
        name = ""
        orcid = ""


        strong_tag = div.find("strong")
        if strong_tag:
            name=strong_tag.get_text(strip=True)
        orcid_tag = div.find("a", href=lambda x: x and "orcid.org" in x)
        if orcid_tag:
            orcid = orcid_tag.get("href", "").strip()



        affil = affil_tags[i].get_text(strip=True) if i < len(affil_tags) else ""

        authors.append((name, affil, orcid))
    

    doi_tag = soup.find("a", href=lambda x: x and "doi.org" in x)
    doi = doi_tag.text.strip() if doi_tag else ""


    abstract = ""
    abs_div = soup.find("div", class_="article-abstract")
    if abs_div:
        p = abs_div.find("p")
        abstract = p.text.strip().replace("<", "").replace(">", "") if p else ""


    pub_year = None
    breadcrumb_items = soup.select("ol.breadcrumb li")
    if len(breadcrumb_items) >= 3:
        vol_text = breadcrumb_items[2].get_text()
        for y in TARGET_YEARS:
            if y in vol_text:
                pub_year = y
                break

    if not pub_year:
        pub_tag = soup.find("div", class_="published")
        if pub_tag:
            for part in pub_tag.text.strip().split():
                if part.isdigit() and len(part) == 4 and part in TARGET_YEARS:
                    pub_year = part
                    break

    if not pub_year:
        meta = soup.find("meta", attrs={"name": "DC.Date"})
        if meta and meta.get("content"):
            year_candidate = meta["content"][:4]
            if year_candidate in TARGET_YEARS:
                pub_year = year_candidate

    if pub_year not in TARGET_YEARS:
        return None


    keywords = ""
    keyword_divs = soup.select("div.keyword-item")
    for div in keyword_divs:
        links = div.find_all("a")
        keywords = "|".join([a.text.strip() for a in links])


    ref_tag = soup.find("div", class_="article-references-content")
    references = ref_tag.get_text(separator=" ", strip=True) if ref_tag else ""

    return {
        "title": title or "",
        "authors": authors,
        "doi": doi or "",
        "keywords": keywords or "",
        "abstract": abstract or "",
        "year": pub_year,
        "journal": HARDCODED_JOURNAL_NAME,
        "job_id": article_id,
        "references": references or ""
    }

def create_article_folder(year, journal, title, article_id):    
    safe_journal = sanitize(journal)
    safe_title = sanitize(title)

    folder_name = safe_title if safe_title else str(article_id)
    folder_path = os.path.join(ROOT_FOLDER, year, safe_journal, folder_name)
    os.makedirs(folder_path, exist_ok=True)
    return folder_path


for article_id in range(START_ID, END_ID + 1):
    article_url = ARTICLE_URL_TEMPLATE.format(article_id)
    print(f"\n Checking Article ID: {article_id}")

    metadata = extract_metadata(article_url, article_id)
    if not metadata:
        print("Skipped (no data or not 2024/2025)")
        continue

    print(f"{metadata['year']} | {metadata['title']}")
    article_folder = create_article_folder(metadata["year"], metadata["journal"], metadata["title"], article_id)

    files_info = {"pdf_name": "", "pdf_size": 0}
    article_page = get_soup(article_url) #Intended
    if not article_page: #Intended
        continue #Intended


    with open(os.path.join(article_folder, "page.html"), "w", encoding="utf-8") as f:
        f.write(article_page.prettify())
        
    pdf_link = article_page.select_one("a.galley-link.btn.obj_galley_link.pdf")
    if pdf_link:
        href = pdf_link.get("href")
        name, size = download_file(href, article_url, article_folder)
        files_info["pdf_name"] = name if name else ""
        files_info["pdf_size"] = size
    else:
        files_info["pdf_name"] = ""
        files_info["pdf_size"] = 0

    for link in article_page.select("a[href]"):
        href = link.get("href", "")
        if href.endswith(".xml") or href.endswith(".html"):
            download_file(href, article_url, article_folder)

    generate_xml(metadata, files_info, article_folder)

print("\n Completed extraction for article IDs.")
