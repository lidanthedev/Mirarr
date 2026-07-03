"""Vadapav provider for https://vadapav.mov/."""

from typing import List
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.providers.directory_list_provider import DirectoryListProvider, FileEntry


class VadapavProvider(DirectoryListProvider):
    """Vadapav provider for https://vadapav.mov/.

    Uses list-based HTML format for directory listings.
    """

    @property
    def name(self) -> str:
        return "VadapavProvider"

    @property
    def base_url(self) -> str:
        return "https://vadapav.mov"

    @property
    def movies_path(self) -> str:
        return "/movies"

    @property
    def tv_path(self) -> str:
        return "/shows"

    async def _parse_directory_html(self, html: str, base_url: str) -> List[FileEntry]:
        """Parse list-based HTML format.

        Format:
        <li class="file-entry">
            <div class="name-div">
                <a class="directory-entry" href="/path">Name</a>
            </div>
            <div>Size</div>
        </li>
        """
        results = []
        soup = BeautifulSoup(html, "html.parser")

        file_entries = soup.find_all("li", class_="file-entry")

        for entry in file_entries:
            link_tag = entry.find("a", class_="directory-entry")

            if link_tag:
                name = link_tag.get_text(strip=True)
                path = urljoin(base_url, link_tag.get("href"))

                # Get the size from the sibling div
                name_div = entry.find("div", class_="name-div")
                size_div = name_div.find_next_sibling("div") if name_div else None

                size_text = size_div.get_text(strip=True) if size_div else "-"
                if size_text == "-":
                    size = 0.0
                else:
                    try:
                        size = float(size_text)
                    except ValueError:
                        size = 0.0

                results.append(FileEntry(name=name, path=path, size=size))

        return results
