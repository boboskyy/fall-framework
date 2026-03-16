from core.server import create_app
from detector import ItskyledcYolov12MediapipeDetector

app = create_app(ItskyledcYolov12MediapipeDetector)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
