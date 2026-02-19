from core.server import create_app
from detector import BoboskyyFallDetector

app = create_app(BoboskyyFallDetector)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
