from dataclasses import dataclass
import hashlib
import logging
import os
import time
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup


class DownloaderException(Exception):
    pass


@dataclass
class DownloadItem:
    year: int
    month: int
    href: str


class DownloaderApp:

    PAGE_ROOT = "https://boli-blog.pl/"
    DOWNLOAD_TIMEOUT = 10
    DOWNLOAD_DELAY = 0

    CACHE_DIR = "cache"
    IMAGES_DIR = "images"

    FILTER_LIST = ["http://nedroid.com/"]

    CONTENT_SOURCES = [
        "googleusercontent.com",
        "blogspot.com",
    ]

    def __init__(self) -> None:
        self.__logger = logging.getLogger(f"DownloaderApp{id(self)}")

    def run(self) -> int:
        self.__logger.debug("run()")

        try:
            os.makedirs(self.CACHE_DIR, exist_ok=True)
            os.makedirs(self.IMAGES_DIR, exist_ok=True)

            items = self.__download_root_page()
            # items = [
            #     DownloadItem(2023, 10, "https://boli-blog.pl/2023/10/"),
            #     DownloadItem(2011, 4, "https://boli-blog.pl/2011/04/"),
            # ]

            self.__process_items(items)

        except (DownloaderException, requests.HTTPError):
            self.__logger.exception("Download files due to exception")
            return 1

        return 0

    def __process_items(self, items: list[DownloadItem]) -> None:
        self.__logger.debug(f"process_items() count={len(items)}")

        if len(items) == 0:
            return

        last_item = items.pop()

        for item in items:
            self.__process_item(item)

        self.__process_item(last_item, refresh=True)

    def __process_item(self, item: DownloadItem, refresh: bool = False) -> None:
        self.__logger.debug(f"process_item() item={item} refresh={refresh}")

        page_text = self.__download_page(
            item.href, use_cache=False if refresh else True
        )

        soup = BeautifulSoup(page_text, "html.parser")

        articles = soup.find_all("article", attrs={"class": "post"})
        for article in articles:
            try:
                post_id = article.attrs["id"]
            except KeyError as e:
                raise DownloaderException(f"Article missing ID: {article}") from e

            title = article.find("h1", attrs={"class": "entry-title"})
            if title is None:
                raise DownloaderException(
                    f"Article title not found in article: {article}"
                )

            article_a = title.find("a")
            if article_a is None:
                raise DownloaderException(
                    f"Article address not found in article: {article}"
                )

            try:
                post_href = article_a.attrs["href"]
            except KeyError as e:
                raise DownloaderException(
                    f"Article address missing HREF: {article}"
                ) from e

            self.__process_post(item, post_id, post_href)

    def __process_post(self, item: DownloadItem, post_id: str, post_href: str):
        self.__logger.debug(f"process_post() id={post_id} post_href={post_href}")

        id_tokens = post_id.split("-")
        if len(id_tokens) != 2:
            raise DownloaderException(f"Unsupported ID format: {post_id}")

        id_string = f"{int(id_tokens[1]):010d}"

        self.__logger.debug(f"process_post() - calculated ID: {id_string}")

        page_text = self.__download_page(post_href)

        soup = BeautifulSoup(page_text, "html.parser")

        content = soup.find("div", attrs={"class": "entry-content"})
        if content is None:
            raise DownloaderException("Content not found")

        image_sources = []

        images = content.find_all("img")
        for image in images:
            self.__logger.debug(f"process_post() image found: {image}")

            try:
                image_src = image.attrs["src"]
            except KeyError as e:
                raise DownloaderException(f"Image missing SRC: {image}") from e

            image_sources.append(image_src)

            image_parent = image.parent

            self.__logger.debug(f"Image parent: {image_parent}")

            if image_parent.name != "a":
                continue

            try:
                parent_href = image_parent.attrs["href"]
            except KeyError as e:
                raise DownloaderException(f"Image parent missing SRC: {image}") from e

            image_sources.append(parent_href)

        subid = 0
        for image_source in image_sources:
            self.__logger.debug(f"process_post() processing image: {image_sources}")

            # skip = False
            # for filter_prefix in self.FILTER_LIST:
            #     if image_source.startswith(filter_prefix):
            #         skip = True
            #         break
            # if skip:
            #     continue

            source_valid = False
            for source in self.CONTENT_SOURCES:
                if image_source.find(source) >= 0:
                    source_valid = True
                    break
            if not source_valid:
                self.__logger.info(f"Skipping: {image_source} from {post_href}")
                continue

            image_data = self.__download_image(image_source)

            subset = image_data[0:32]

            ext = ".dat"

            if subset[0:4] == b"\x89PNG":
                ext = ".png"
            elif subset[0:10] == b"\xff\xd8\xff\xe0\x00\x10JFIF":
                ext = ".jpg"
            elif subset[0:6] == b"GIF89a":
                ext = ".gif"
            else:
                self.__logger.debug(
                    f"Mime unknown: {image_source} from {post_href} bytes {subset}"
                )

            if ext == ".dat":
                path = urlparse(image_source).path
                ext = os.path.splitext(path)[1]
                if len(ext) == 0:
                    ext = ".dat"

                    if ext == ".dat":
                        self.__logger.debug(
                            f"Mime unknown: {image_source} from {post_href} bytes {subset}"
                        )

            self.__logger.debug(f"process_post() image extension: {ext}")

            file_name = f"{item.year:04d}-{item.month:02d}-{id_string}-{subid:04d}"
            subid = subid + 1

            file_path = f"{self.IMAGES_DIR}/{file_name}{ext}"

            self.__logger.debug(f"process_post() file path: {file_path}")

            with open(file_path, mode="wb") as image_file:
                image_file.write(image_data)

    def __download_root_page(self) -> list[DownloadItem]:
        self.__logger.debug("download_root_page()")

        page_text = self.__download_page(self.PAGE_ROOT)

        soup = BeautifulSoup(page_text, "html.parser")

        archive = soup.find("aside", attrs={"class": "widget_archive"})
        if archive is None:
            raise DownloaderException("Archive not found")

        archive_list = archive.find_all("a")
        if archive_list is None:
            raise DownloaderException("Archive list is invalid")

        items = []
        for archive_item in reversed(archive_list):
            try:
                item_address = archive_item.attrs["href"]
            except KeyError as e:
                raise DownloaderException("Archive list item missing HREF") from e

            tokens = list(reversed(list(filter(None, item_address.split("/")))))

            item = DownloadItem(int(tokens[1]), int(tokens[0]), item_address)

            self.__logger.debug(f"download_root_page() - found item: {item}")

            items.append(item)

        return items

    def __download_page(self, href: str, use_cache: bool = True) -> str:
        self.__logger.debug(f"download_page() href={href} use_cache={use_cache}")

        file_name = href.replace(":", "_").replace("/", "_")
        file_path = f"{self.CACHE_DIR}/{file_name}.html"

        if use_cache:
            if os.path.isfile(file_path):
                self.__logger.debug(f"download_page() - reading from file: {file_path}")

                with open(file_path, mode="rt", encoding="utf-8") as data_file:
                    return data_file.read()

        self.__logger.debug(f"download_page() - reading from HREF: {href}")

        response = self.__request_data(href)

        with open(file_path, mode="wt", encoding="utf-8") as page_file:
            page_file.write(response.text)

        return response.text

    def __download_image(self, href: str, use_cache: bool = True) -> bytes:
        self.__logger.debug(f"download_image() href={href} use_cache={use_cache}")

        file_hash = hashlib.sha256(href.encode()).hexdigest()
        file_path = f"{self.CACHE_DIR}/{file_hash}.bin"

        if use_cache:
            if os.path.isfile(file_path):
                self.__logger.debug(
                    f"download_image() - reading from file: {file_path}"
                )

                with open(file_path, mode="rb") as data_file:
                    return data_file.read()

        self.__logger.debug(f"download_image() - reading from HREF: {href}")

        response = self.__request_data(href)

        with open(file_path, mode="wb") as test_file:
            test_file.write(response.content)

        return response.content

    def __request_data(self, href: str):
        response = requests.get(href, timeout=self.DOWNLOAD_TIMEOUT)
        response.raise_for_status()

        if self.DOWNLOAD_DELAY > 0:
            time.sleep(self.DOWNLOAD_DELAY)

        return response
