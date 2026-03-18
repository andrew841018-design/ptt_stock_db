## import libraries
import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime
from config import SKIP_KEYWORDS, TABLE_ARTICLE, TABLE_COMMENT
from db_helper import get_db
# functions
def get_previous_page(soup):
    for item in soup:
        prev_soup=item.find("a",string=lambda t:t and "上頁" in t)
        if not prev_soup:
            continue
        else:
            prev_page=prev_soup.get("href")
            return prev_page
    return False
def _is_duplicate(cursor, article_url):
    cursor.execute(f"SELECT Article_id FROM {TABLE_ARTICLE} WHERE Url=?", (article_url,))
    return cursor.fetchone() is not None

def _insert_article(cursor, article_data):
    cursor.execute(f"""
        INSERT INTO {TABLE_ARTICLE}
        (Title,Push_count,Author,Url,Date,Content,Scraped_time)
        VALUES (?,?,?,?,?,?,?)""",
        (article_data["Title"], article_data["Push_count"], article_data["Author"],
         article_data["Url"], article_data["Date"], article_data["Content"], article_data["Scraped_time"]))
    return cursor.lastrowid

def _insert_comments(cursor, article_id, comments):
    for comment in comments:
        cursor.execute(f"""
            INSERT INTO {TABLE_COMMENT}
            (Article_id,User_id,Push_tag,Message)
            VALUES (?,?,?,?)""",
            (article_id, comment["User_id"], comment["Push_tag"], comment["Message"]))

def scrape_web_page_title(headers, url):
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    data = soup.find_all("div", class_="r-ent")
    if not data:
        return False
    with get_db() as conn:
        cursor = conn.cursor()
        for item in data:
            comment = item.find("div", class_="nrec")
            title = item.find("div", class_="title")
            author = item.find("div", class_="author")
            date = item.find("div", class_="date")
            a_tag = title.find("a")
            if not a_tag:
                continue
            article_url = "https://www.ptt.cc" + a_tag.get("href")
            if any(keyword in title.text for keyword in SKIP_KEYWORDS):
                continue
            if _is_duplicate(cursor, article_url):
                continue
            web_page_content = scrape_web_page_content(headers, article_url)
            if not web_page_content:
                continue
            comment_txt = comment.text.strip() if comment and comment.text.strip() else "0"
            article_data = {
                "Title": title.text.strip(),
                "Push_count": comment_txt,
                "Author": author.text.strip(),
                "Url": article_url,
                "Date": date.text.strip(),
                "Content": web_page_content["Content"],
                "Scraped_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            article_id = _insert_article(cursor, article_data)
            _insert_comments(cursor, article_id, web_page_content["Comment_info"])
    return True
def scrape_web_page_content(headers,url):
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    main_content=soup.find("div",id="main-content")
    article_content=[]
    comment_info=[]
    if main_content:
        #get comment_info
        for item in main_content.find_all("div",class_="push"):
            message=item.find("span",class_="push-content")
            user_id=item.find("span",class_="push-userid")
            pro_and_con=item.find("span",class_="push-tag")
            if not (message and user_id and pro_and_con):
                continue
            content_dict={
                "User_id":user_id.text.strip(),
                "Push_tag":pro_and_con.text.strip(),
                "Message":message.text.strip(),
            }
            comment_info.append(content_dict)
        #get content of the article
        for item in main_content.find_all("div",class_="push"):#刪除推文
            item.decompose()
        for item in main_content.find_all("div",class_=lambda c:c and "article" in c):#標題相關資訊刪除
            item.decompose()
        for item in main_content.find_all("span",class_="f2"):#remove 發信站＋文章網址
            item.decompose()
        for line in main_content.text.strip().split("\n"):
            if("引述" in line):
                continue
            if(line.startswith(": ") or line.startswith("http")):
                continue
            if line.strip():
                article_content.append(line.strip())
        article_content="\n".join(article_content)
        time.sleep(0.3) 
        return {"Content":article_content,"Comment_info":comment_info}
    else:
        return False