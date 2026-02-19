"""Flask app for dzungvpham_twostream_cnn detector."""

from core.server import create_app
from detector import DzungvphamTwoStreamCnnDetector

app = create_app(DzungvphamTwoStreamCnnDetector)
