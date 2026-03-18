import jieba
import re
import os
from ptt_sentiment_dict import POSITIVE_WORDS, NEGATIVE_WORDS

jieba.load_userdict(os.path.join(os.path.dirname(__file__), "user_dict.txt"))#載入自定義規則（用詞，詞頻，詞性）

_words_loaded = False

def _ensure_words_loaded():
    global _words_loaded
    if _words_loaded:
        return
    base_dir = os.path.dirname(__file__)
    with open(os.path.join(base_dir, 'ntusd-positive.txt'), 'r', encoding='utf-8') as f:
        for line in f:
            POSITIVE_WORDS.add(line.strip())
    with open(os.path.join(base_dir, 'ntusd-negative.txt'), 'r', encoding='utf-8') as f:
        for line in f:
            NEGATIVE_WORDS.add(line.strip())
    _words_loaded = True

def calculate_sentiment(text):
    _ensure_words_loaded()
    words=jieba.cut(text)
    words=[w for w in words if re.match(r'[\u4e00-\u9fff a-zA-Z0-9]+',w)]
    sentiment=0
    for word in words:
        if word in POSITIVE_WORDS:
            sentiment+=1
        elif word in NEGATIVE_WORDS:
            sentiment-=1
    return sentiment
