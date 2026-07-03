"""A111477 provider for https://a.111477.xyz/."""

from typing import Any
from typing import List
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.providers.directory_list_provider import DirectoryListProvider, FileEntry


class A111477Provider(DirectoryListProvider):
    """A111477 provider for https://a.111477.xyz/.

    Uses table-based HTML format for directory listings.
    """

    @property
    def name(self) -> str:
        return "A111477Provider"

    @property
    def base_url(self) -> str:
        return "https://a.111477.xyz"

    @property
    def movies_path(self) -> str:
        return "/movies"

    @property
    def tv_path(self) -> str:
        return "/tvs"

    async def _parse_directory_html(self, html: str, base_url: str) -> List[FileEntry]:
        """Parse table-based HTML format.

        Format:
        <table id="fileTable">
            <tr data-entry="true" data-name="foo" data-url="/foo/">
                <td class="size" data-sort="-1">-</td>
            </tr>
        </table>
        """
        results = []
        soup = BeautifulSoup(html, "html.parser")

        # Find all table rows with data-entry="true"
        file_entries = soup.find_all("tr", attrs={"data-entry": "true"})

        for entry in file_entries:
            # Get name and URL from data attributes
            name = entry.get("data-name", "")
            url_path = entry.get("data-url", "")

            if name and url_path:
                path = urljoin(base_url, url_path)

                # Get size from td.size data-sort attribute (byte value)
                size_td = entry.find("td", class_="size")
                size_sort = size_td.get("data-sort", "-1") if size_td else "-1"

                try:
                    size = float(size_sort)
                    if size < 0:
                        size = 0.0
                except ValueError:
                    size = 0.0

                results.append(FileEntry(name=name, path=path, size=size))

        return results

    def get_yt_opts(self) -> dict[str, Any]:
        opts = super().get_yt_opts()
        opts["concurrent_fragment_downloads"] = 10
        return opts
