from .base import BaseAdapter, Prospect
from .github import GitHubAdapter
from .hn import HackerNewsAdapter
from .x_twitter import XTwitterAdapter
from .bootcamps import BootcampAdapter

ADAPTERS = {
    "github": GitHubAdapter,
    "hackernews": HackerNewsAdapter,
    "x_twitter": XTwitterAdapter,
    "bootcamps": BootcampAdapter,
}
