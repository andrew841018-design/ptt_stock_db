import re
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator


class CommentSchema(BaseModel):
    author:   str
    push_tag: str
    message:  str


class ArticleSchema(BaseModel):
    title:        str
    content:      str
    url:          str
    author:       Optional[str]
    published_at: datetime
    push_count:   Optional[int]
    comments:     list[CommentSchema] = []

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, title):
        if not title.strip():
            raise ValueError("title cannot be empty")
        return title

    @field_validator("url")
    @classmethod
    def url_must_be_valid(cls, url):
        if not re.match(r"https?://", url):
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
