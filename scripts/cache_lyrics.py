""" Simple cache script, intended to be run explicitly by the user. """
import argparse
import logging
from pathlib import Path

import sys

sys.path.append(str(Path(__file__).parent.parent))

from models import Config
from services.lrc_gather import LRCLIBGatherer


def setup_logging():
    """ Setup logging. """
    log_dir = Path('logs')
    log_dir.mkdir(exist_ok=True)

    log_file = log_dir / 'cache_lyrics.log'

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )


def main():
    parser = argparse.ArgumentParser(description="Cache lyrics for your music library")
    args = parser.parse_args()

    setup_logging()

    config = Config()

    print("Starting lyrics caching...")
    gatherer = LRCLIBGatherer(config)

    try:
        gatherer.gather_lyrics_all()
    except KeyboardInterrupt:
        print("\n\nCancelled by user")


if __name__ == '__main__':
    main()
