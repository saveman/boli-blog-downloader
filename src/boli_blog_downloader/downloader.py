import sys

from boli_blog_downloader.app import DownloaderApp


def run_downloader():
    sys.exit(DownloaderApp().run())
