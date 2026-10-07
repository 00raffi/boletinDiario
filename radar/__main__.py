import argparse
import os

import uvicorn


def main():
    parser = argparse.ArgumentParser(description="Paper Radar: interfaz local y coordinador diario")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    os.umask(0o077)
    uvicorn.run("radar.app:create_app", factory=True, host="127.0.0.1", port=args.port, workers=1)


if __name__ == "__main__":
    main()
