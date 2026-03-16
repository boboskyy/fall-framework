from core.server import create_app
from detector import ParichehrvnTcnFallDetector

app = create_app(ParichehrvnTcnFallDetector)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
