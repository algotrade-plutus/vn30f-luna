"""Docker healthcheck for the private dashboard container."""

from urllib.request import urlopen


def main() -> None:
    with urlopen("http://127.0.0.1:8080/healthz", timeout=2) as response:
        raise SystemExit(0 if response.status == 200 else 1)


if __name__ == "__main__":
    main()
