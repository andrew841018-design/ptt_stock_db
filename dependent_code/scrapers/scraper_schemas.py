import re
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator


class CommentSchema(BaseModel):
    """
    PTT 推文（留言）格式驗證。
    只有 PTT 爬蟲會用到；其他來源的 comments 欄位回傳空 list，不會觸發此 schema。
    """
    user_id:  str   # 推文者 ID（PTT 帳號）
    push_tag: str   # 推文類型：推 / 噓 / →（未驗證值域，保持通用性）
    message:  str   # 推文內容


class ArticleSchema(BaseModel):
    title:        str
    content:      str
    url:          str
    author:       Optional[str]
    published_at: datetime
    push_count:   Optional[int]
    comments:     list[CommentSchema] = []

    @field_validator("title") #要測試的欄位名稱
    @classmethod # 固定寫法PyDantic規範
    def title_not_empty(cls, title):
        if not title.strip():
            raise ValueError("title cannot be empty")
        return title

    @field_validator("url")
    @classmethod
    def url_must_be_valid(cls, url):
        if not re.match(r"https?://", url):# ?-前一個字元可有可無，https或http,re.match-從字串開頭比對
            raise ValueError(f"invalid url: {url!r}")
        return url

    @field_validator("push_count")
    @classmethod
    def push_count_in_range(cls, push_count):
        if push_count is not None and not (-100 <= push_count <= 100):
            raise ValueError(f"push_count must be between -100 and 100, got {push_count}")
        return push_count

    @field_validator("published_at")
    @classmethod
    def published_at_not_future(cls, published_at):
        if published_at > datetime.utcnow():
            raise ValueError(f"published_at is in the future: {published_at}")
        return published_at
