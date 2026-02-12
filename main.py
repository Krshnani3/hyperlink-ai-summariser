from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request

templates = Jinja2Templates(directory="templates")

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time


import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from fastapi import FastAPI
from dotenv import load_dotenv
from openai import OpenAI
from readability import Document
from datetime import datetime


load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(title="Hyperlink AI Summariser")

from urllib.parse import urljoin

def extract_hyperlinks(page_url, target_date):

    day = str(int(target_date.day))
    month = str(int(target_date.month))
    year = str(target_date.year)

    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service

    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--remote-debugging-port=9222")

    service = Service("/usr/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=options)


    # options.add_argument("--headless")  # Uncomment later if you want background mode

    try:
        driver.get(page_url)

        wait = WebDriverWait(driver, 30)
        WebDriverWait(driver, 30).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )


        # Select Year
        Select(wait.until(
            EC.presence_of_element_located((By.ID, "ContentPlaceHolder1_ddlYear"))
        )).select_by_value(year)

        time.sleep(2)

        # Select Month
        Select(wait.until(
            EC.presence_of_element_located((By.ID, "ContentPlaceHolder1_ddlMonth"))
        )).select_by_value(month)

        time.sleep(2)

        # Select Day
        Select(wait.until(
            EC.presence_of_element_located((By.ID, "ContentPlaceHolder1_ddlday"))
        )).select_by_value(day)

        time.sleep(4)

        anchors = driver.find_elements(By.TAG_NAME, "a")

        links = []
        seen = set()

        for a in anchors:
            href = a.get_attribute("href")

            if not href:
                continue

            if "PressReleasePage.aspx?PRID=" not in href:
                continue

            if href in seen:
                continue

            seen.add(href)

            links.append({
                "title": a.text.strip(),
                "url": href
            })

        print(f"Extracted {len(links)} press releases for {day}-{month}-{year}")

        return links

    finally:
        driver.quit()


def extract_page_content(url):
    response = requests.get(url, timeout=10)
    response.raise_for_status()

    # Parse ORIGINAL HTML first
    full_soup = BeautifulSoup(response.text, "html.parser")

    # ---- Extract Date from dedicated PIB div ----
    date_value = "Date N/A"

    date_div = full_soup.find("div", id="PrDateTime")

    if date_div:
        text = date_div.get_text(strip=True)
        cleaned = text.replace("Posted On:", "").split("by")[0].strip()
        date_value = " ".join(cleaned.split()[:3])

    # ---- Extract Ministry Name from original DOM ----
    ministry_tag = full_soup.find(id="MinistryName")

    if ministry_tag and ministry_tag.get_text(strip=True):
        ministry = ministry_tag.get_text(strip=True)
    else:
        ministry = "Government of India"

    # ---- Now extract cleaned article text ----
    doc = Document(response.text)
    cleaned_html = doc.summary()
    cleaned_soup = BeautifulSoup(cleaned_html, "html.parser")

    text = " ".join(
        p.get_text(strip=True)
        for p in cleaned_soup.find_all("p")
    )

    return ministry, text, date_value


def ai_summarize(text):
    prompt = f"""
    Rewrite the following government press release into:

    1. A catchy, short headline (maximum 8-10 words)
       - Youth-friendly
       - Catchy and quick to read
       - Sharp, crisp and scroll-stopping
       - Language should still be formal and appropriate for government use
       - Headline should include name of related ministry issuing the press release or the post of the government functionary who is the subject of the press release


    2. A punchy summary (maximum 60-80 words)
       - Summarize in about 60 to 80 words
       - Use short but complete sentences that are quick to read and easy to understand
       - Use crisp and catchy language suited for youth target audience

    Format strictly like this:

    HEADLINE:
    <headline here>

    SUMMARY:
    <summary here>

    Content:
    {text}
    """

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "You turn policy content into short, catchy youth-friendly news posts."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.6,
        max_tokens=200
    )

    output = response.choices[0].message.content.strip()

    # Extract headline and summary
    headline = ""
    summary = ""

    if "HEADLINE:" in output and "SUMMARY:" in output:
        parts = output.split("SUMMARY:")
        headline = parts[0].replace("HEADLINE:", "").strip()
        summary = parts[1].strip()
    else:
        summary = output

    return headline, summary

import json
import re

def ai_score_headlines(items):
    """
    AI assigns importance score (1–10) to each headline.
    Returns scores in SAME ORDER as input.
    """

    combined_text = ""

    for idx, item in enumerate(items):
        combined_text += f"""
        ITEM {idx+1}:
        Headline: {item['headline']}
        """

    prompt = f"""
    You are a senior Indian public policy analyst.
    Below are government press release headlines.

    For EACH headline assign an Importance Score from 1 to 10 based on:
    You are a senior Indian public policy analyst.
    Below are government press release headlines.

    Consider:
    - Economic development, industrial growth & agriculture
    - National security, unity, integrity & sovereignty
    - Social capital, cohesion & harmony
    - Strategic/geopolitical importance
    - Long-term developmental significance
    - Urgency and scale of impact

    Also follow:
    - Base judgement ONLY on the headline.
    - Do not assume facts beyond headline.
    - May take into consideration the ministry or government executive post named in the headline.

    IMPORTANT RULES:
    - Score ONLY based on headline text.
    - Do NOT reorder items.
    - Output scores in SAME ORDER as input.

    Return STRICT JSON ONLY in this format:

    [
      {{"importance_score": 7}},
      {{"importance_score": 4}},
      {{"importance_score": 9}}
    ]

    Content:
    {combined_text}
    """

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "You evaluate importance of policy announcements."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
        max_tokens=1200
    )

    raw_output = response.choices[0].message.content.strip()

    # --- SAFE JSON EXTRACTION ---
    try:
        match = re.search(r"\[.*\]", raw_output, re.DOTALL)
        if not match:
            raise ValueError("No JSON array found")
        scores = json.loads(match.group())
    except Exception as e:
        print("AI scoring JSON error:", e)
        print("RAW OUTPUT:", raw_output)
        scores = []

    return scores



from datetime import datetime

@app.get("/summarise-links")
def summarise_links(limit: int = 100, date: str = None):

    page_url = "https://www.pib.gov.in/Allrel.aspx?reg=3&lang=1"

    if not date:
        return {"message": "Date parameter required.", "items": []}

    try:
        target_date = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return {"message": "Invalid date format. Use YYYY-MM-DD.", "items": []}
    
    limit = min(limit, 25)

    links = extract_hyperlinks(page_url, target_date)

    if not links:
        return {"message": "No press releases found.", "items": []}

    results = []

    for link in links[:limit]:
        try:
            ministry, text, date_value = extract_page_content(link["url"])
            headline, summary = ai_summarize(text)

            results.append({
                "ministry": ministry,
                "headline": headline,
                "url": link["url"],
                "date": date_value,
                "summary": summary
            })

        except Exception as e:
            print("Error occurred:", e)
            continue

    # -------- AI IMPORTANCE SCORING --------

    scoring_input = [{"headline": item["headline"]} for item in results]

    try:
        scores = ai_score_headlines(scoring_input)

        if len(scores) != len(results):
            print("Score count mismatch — skipping ranking")
        else:
            for i, score_obj in enumerate(scores):
                results[i]["importance_score"] = score_obj.get("importance_score", 0)

        # sort only if scores valid
            results = sorted(
                results,
                key=lambda x: x.get("importance_score", 0),
                reverse=True
            )

    except Exception as e:
        print("Scoring failed:", e)

    
    return {"items": results}





@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

