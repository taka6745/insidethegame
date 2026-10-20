"""Bounded startup gate for the two Microsoft messaging emulators."""
import time
from urllib.error import URLError
from urllib.request import urlopen


def wait_for_emulator(name, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(f'http://{name}:5300/health', timeout=5) as response:
                if response.status == 200:
                    print(f'{name} ready', flush=True)
                    return
        except (URLError, TimeoutError):
            pass
        time.sleep(2)
    raise TimeoutError(f'{name} did not become healthy within {timeout}s')


if __name__ == '__main__':
    for service in ('eventhubs', 'servicebus'):
        wait_for_emulator(service)
