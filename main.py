from bs4 import BeautifulSoup
from flask import Flask, jsonify, request
import re
import requests
import json

app = Flask(__name__)

# Get DATABASE_URL from environment variables
DATABASE_URL = os.environ.get("DATABASE_URL")

# Connect to the database
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

# Create table if not exists
def ensure_table_exists():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS craigslist_listings (
                    id SERIAL PRIMARY KEY,
                    title TEXT,
                    url TEXT,
                    price TEXT,
                    posted_at TEXT
                );
            """)
        conn.commit()

ensure_table_exists()

@app.route('/')
def hello_world():
    return "<h1>Craigslist Scraper Running</h1>"


@app.route("/scrape", methods=["POST"])
def scrape():
    data = request.get_json(force=True) or {}
    region = data.get("region", "philadelphia").lower()
    max_price = data.get("max_price", "1200")
    keywords = data.get("keywords", "")

    url = f"https://{region}.craigslist.org/search/sub?max_price={max_price}&query={keywords}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")
    listings = []

    for li in soup.find_all("li"):
        a_tag = li.find("a", href=True)
        if not a_tag or not a_tag.text.strip():
            continue

        raw_title = a_tag.text.strip()
        title = re.sub(r"\s+", " ", raw_title)
        full_text = li.get_text(" ", strip=True)
        matches = re.findall(r"\$\d{2,5}", full_text)
        price = matches[-1] if matches else "N/A"

        link = a_tag.get("href", "No link")

        # --------------------------
        # NEW: Fetch full listing page for postedAt
        # --------------------------
        posted_at = "N/A"
        try:
            detail_res = requests.get(link, headers=headers)
            detail_soup = BeautifulSoup(detail_res.text, "html.parser")

            # First attempt: Try structured data
            script_tag = detail_soup.find("script", id="ld_posting_data")
            if script_tag:
                import json  # make sure this is at the top of your file too
                ld_json = json.loads(script_tag.string)
                posted_at = ld_json.get("datePosted", "N/A")

            # Fallback: Try <p class="postinginfo">
            if posted_at == "N/A":
                postinginfo_tags = detail_soup.find_all("p",
                                                        class_="postinginfo")
                for tag in postinginfo_tags:
                    if "posted:" in tag.text.lower():
                        posted_at = tag.text.strip().replace("posted: ", "")

                        break

        except Exception as e:
            print(f"Failed to fetch postedAt for {link}: {e}")

        listings.append({
            "title": title,
            "url": link,
            "price": price,
            "postedAt": posted_at
        })

        try:
                with get_db_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO craigslist_listings (title, url, price, posted_at)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (url) DO NOTHING;
                        """, (title, link, price, posted_at))
                    conn.commit()
        except Exception as e:
            print(f"Failed to insert listing into DB: {e}")

    return jsonify(listings)  # return top 10 only


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
