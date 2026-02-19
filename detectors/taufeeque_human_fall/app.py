from core.server import create_app
from detector import TaufeequeHumanFallDetector

app = create_app(TaufeequeHumanFallDetector)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
