import time
import sqlite3
from typing import List, Dict

import requests
from bs4 import BeautifulSoup


# 設定
ORG_NAME = "google"
BASE_URL = "https://github.com"
ORG_REPOS_URL = f"{BASE_URL}/{ORG_NAME}?tab=repositories"
DB_PATH = "google_github_repos.db"
TABLE_NAME = "google_repositories"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

REQUEST_TIMEOUT = 15
SLEEP_SEC = 1  # 1秒スリープ（スクレイピングのマナーとしてサーバー負荷を軽減）


def create_database(db_path: str = DB_PATH) -> sqlite3.Connection:
    """データベースと保存用テーブルを作成する"""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repository_name TEXT NOT NULL,
            primary_language TEXT,
            star_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
        """
    )
    conn.commit()
    return conn


def parse_star_count(text: str) -> int:
    """スター数のテキストを整数に変換する（例: '1.2k' -> 1200, '1,234' -> 1234）"""
    text = text.strip().replace(",", "")
    if not text:
        return 0
    try:
        return int(text)
    except ValueError:
        pass
    multipliers = {"k": 1_000, "K": 1_000, "m": 1_000_000, "M": 1_000_000}
    if text and text[-1] in multipliers:
        return int(float(text[:-1]) * multipliers[text[-1]])
    return 0


def scrape_repositories() -> List[Dict]:
    """Google組織のリポジトリ一覧ページをスクレイピングしてデータを返す"""
    repos: List[Dict] = []
    page = 1

    while True:
        url = ORG_REPOS_URL if page == 1 else f"{ORG_REPOS_URL}&page={page}"
        print(f"[スクレイピング] {url}")

        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            print(f"[警告] ページ {page} の取得に失敗しました（ステータスコード: {response.status_code}）")
            break

        soup = BeautifulSoup(response.text, "html.parser")

        # リポジトリのリストアイテムを抽出（GitHubのHTML構造に依存）
        items = soup.select("article.Box-row, div.Box-row, li.repo-list-item")

        if not items:
            print(f"[情報] ページ {page} にリポジトリが見つかりませんでした。処理を終了します。")
            break

        for item in items:
            # --- リポジトリ名 ---
            name_link = None
            for a in item.select("a"):
                href = a.get("href", "")
                if href.startswith(f"/{ORG_NAME}/") and href.count("/") == 2:
                    name_link = a
                    break
            if not name_link:
                name_link = item.select_one("h3 a, h2 a, a")

            href = name_link.get("href", "") if name_link else ""
            repo_name = href.split("/")[-1] if href else name_link.get_text(strip=True) if name_link else ""
            if not repo_name or repo_name == ORG_NAME:
                continue

            # --- 主要言語 ---
            lang_el = item.select_one("span[itemprop='programmingLanguage']")
            if not lang_el:
                lang_el = item.select_one("span.ml-0, span.f6 .mr-1")
            primary_language = lang_el.get_text(strip=True) if lang_el else None

            # --- スター数 ---
            star_el = item.select_one("a[href*='/stargazers'] .Counter, .Counter")
            star_count = parse_star_count(star_el.get_text(strip=True)) if star_el else 0

            repos.append(
                {
                    "repository_name": repo_name,
                    "primary_language": primary_language,
                    "star_count": star_count,
                }
            )

        print(f"[情報] ページ {page}: {len(items)} 件取得（累計 {len(repos)} 件）")
        page += 1

        # 1秒スリープ（サーバー負荷軽減のため必須）
        time.sleep(SLEEP_SEC)

        # 安全のためページ数制限（必要に応じて調整・削除してください）
        if page > 50:
            print("[情報] ページ上限（50ページ）に達しました。")
            break

    return repos


def save_to_database(repos: List[Dict], conn: sqlite3.Connection, db_path: str = DB_PATH) -> None:
    """スクレイピングしたデータをデータベースに保存する"""
    cur = conn.cursor()
    cur.execute(f"DELETE FROM {TABLE_NAME}")  # 実行ごとにリセットして重複を防ぐ
    for repo in repos:
        cur.execute(
            f"""
            INSERT INTO {TABLE_NAME} (repository_name, primary_language, star_count)
            VALUES (?, ?, ?)
            """,
            (
                repo["repository_name"],
                repo["primary_language"],
                repo["star_count"],
            ),
        )
    conn.commit()
    print(f"[保存] {len(repos)} 件をデータベース '{db_path}' のテーブル '{TABLE_NAME}' に保存しました")


def select_and_display(conn: sqlite3.Connection, table_name: str = TABLE_NAME) -> None:
    """保存したデータをSELECT文で表示する"""
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT repository_name, primary_language, star_count
        FROM {table_name}
        ORDER BY star_count DESC, repository_name ASC
        """
    )
    rows = cur.fetchall()

    print("\n" + "=" * 62)
    print("保存済みリポジトリ一覧（スター数降順）")
    print("=" * 62)
    print(f"{'リポジトリ名':<42} | {'主要言語':<12} | {'スター数'}")
    print("-" * 62)
    for repo_name, language, stars in rows:
        lang = language if language else "(不明)"
        print(f"{repo_name:<42} | {lang:<12} | {stars}")
    print("-" * 62)
    print(f"合計: {len(rows)} 件\n")


def main() -> None:
    conn = create_database(DB_PATH)
    try:
        repos = scrape_repositories()
        if repos:
            save_to_database(repos, conn, DB_PATH)
        select_and_display(conn, TABLE_NAME)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
