import jieba
import pandas as pd
import sqlite3
import re
from ptt_sentiment_dict import POSITIVE_WORDS,NEGATIVE_WORDS
jieba.load_userdict("user_dict.txt")#載入自定義規則（用詞，詞頻，詞性）
def calculate_sentiment(text):
    words=jieba.cut(text)
    words=[w for w in words if re.match(r'[\u4e00-\u9fff a-zA-Z0-9]+',w)]
    sentiment=0
    for word in words:
        if word in POSITIVE_WORDS:
            sentiment+=1
        elif word in NEGATIVE_WORDS:
            sentiment-=1
    return sentiment

#把NTUSD結合到ptt sentiment dict
with open('ntusd-positive.txt', 'r',encoding='utf-8') as f:
    for line in f:
        word=line.strip()
        if word not in POSITIVE_WORDS:
            POSITIVE_WORDS.append(word)
with open('ntusd-negative.txt', 'r',encoding='utf-8') as f:
    for line in f:
        word=line.strip()
        if word not in NEGATIVE_WORDS:
            NEGATIVE_WORDS.append(word)