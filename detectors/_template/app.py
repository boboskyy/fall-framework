from core.server import create_app
from detector import {{DETECTOR_CLASS}}

app = create_app({{DETECTOR_CLASS}})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
