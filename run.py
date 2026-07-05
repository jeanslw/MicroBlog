from app import create_app
from config import DEBUG

app = create_app()

if __name__ == "__main__":
    app.run(debug=DEBUG, host="127.0.0.1", port=5000)
