from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re
from urllib.request import Request, urlopen

from .model import Node


@dataclass(frozen=True)
class Brand:
    key: str
    title: str
    color: str
    slug: str
    version: str = "16.29.0"

    @property
    def url(self) -> str:
        return f"https://cdn.jsdelivr.net/npm/simple-icons@{self.version}/icons/{self.slug}.svg"


BRANDS = (
    (r"\bgoogle gemini\b|\bgemini\b", Brand("gemini", "Google Gemini", "#8E75B2", "googlegemini")),
    (r"\bopenai\b|\bchatgpt\b", Brand("openai", "OpenAI", "#10A37F", "openai", "14.15.0")),
    (r"\banthropic\b|\bclaude\b", Brand("anthropic", "Anthropic", "#D97757", "anthropic")),
    (r"\bfastapi\b", Brand("fastapi", "FastAPI", "#009688", "fastapi")),
    (r"\breact(?:\.js)?\b", Brand("react", "React", "#087EA4", "react")),
    (r"\bmariadb\b", Brand("mariadb", "MariaDB", "#003545", "mariadb")),
    (r"\bduckdb\b", Brand("duckdb", "DuckDB", "#F5C400", "duckdb")),
    (r"\bpostgres(?:ql)?\b", Brand("postgresql", "PostgreSQL", "#4169E1", "postgresql")),
    (r"\bmysql\b", Brand("mysql", "MySQL", "#4479A1", "mysql")),
    (r"\bredis\b", Brand("redis", "Redis", "#FF4438", "redis")),
    (
        r"\bamazon web services\b|\baws\b|\bamazon s3\b|\bs3\b|\brds\b",
        Brand("aws", "AWS", "#FF9900", "amazonwebservices", "14.15.0"),
    ),
    (r"\bdocker\b", Brand("docker", "Docker", "#2496ED", "docker")),
    (r"\bgithub\b", Brand("github", "GitHub", "#181717", "github")),
    (r"\bnginx\b", Brand("nginx", "NGINX", "#009639", "nginx")),
    (r"\bcloudflare\b", Brand("cloudflare", "Cloudflare", "#F38020", "cloudflare")),
    (r"\bpython\b", Brand("python", "Python", "#3776AB", "python")),
    (r"\bnode(?:\.js)?\b", Brand("nodejs", "Node.js", "#5FA04E", "nodedotjs")),
    (r"\btypescript\b", Brand("typescript", "TypeScript", "#3178C6", "typescript")),
    (r"\bspring(?: boot)?\b", Brand("spring", "Spring", "#6DB33F", "spring")),
    (r"\bkubernetes\b|\bk8s\b", Brand("kubernetes", "Kubernetes", "#326CE5", "kubernetes")),
    (r"\bterraform\b", Brand("terraform", "Terraform", "#844FBA", "terraform")),
    (r"\bgoogle cloud\b|\bgcp\b", Brand("google-cloud", "Google Cloud", "#4285F4", "googlecloud")),
    (r"\bapache airflow\b|\bairflow\b", Brand("airflow", "Apache Airflow", "#017CEE", "apacheairflow")),
    (r"\bapache kafka\b|\bkafka\b", Brand("kafka", "Apache Kafka", "#231F20", "apachekafka")),
    (r"\bslack\b", Brand("slack", "Slack", "#4A154B", "slack", "14.15.0")),
)


def brand_for_node(node: Node) -> Brand | None:
    text = f"{node.label} {node.subtitle or ''}".lower()
    for pattern, brand in BRANDS:
        if re.search(pattern, text):
            return brand
    return None


@lru_cache(maxsize=64)
def fetch_brand_svg(brand: Brand) -> str | None:
    try:
        request = Request(brand.url, headers={"User-Agent": "repo2drawio/0.8"})
        with urlopen(request, timeout=4) as response:
            raw = response.read(100_001)
    except (OSError, UnicodeError):
        return None
    if len(raw) > 100_000:
        return None
    try:
        svg = raw.decode("utf-8", errors="strict").strip()
    except UnicodeError:
        return None
    lowered = svg.lower()
    if (
        not svg.startswith("<svg")
        or "<script" in lowered
        or "javascript:" in lowered
        or "<image" in lowered
    ):
        return None
    return svg.replace("<svg ", f'<svg fill="{brand.color}" ', 1)
