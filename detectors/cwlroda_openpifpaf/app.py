from core.server import create_app
from detector import CwlrodaOpenpifpafDetector

app = create_app(CwlrodaOpenpifpafDetector)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
