"""Local service entry point with graceful shutdown from the desktop UI."""
import argparse
from pathlib import Path
import uvicorn
from .envfile import load_env_file
from .web import app


def main():
    parser = argparse.ArgumentParser(description='Rezak Studio local desktop service')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    load_env_file(Path(__file__).resolve().parents[1]/'.env')
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.port, workers=1, log_level='info'))
    app.state.shutdown = lambda: setattr(server, 'should_exit', True)
    server.run()


if __name__ == '__main__':
    main()
