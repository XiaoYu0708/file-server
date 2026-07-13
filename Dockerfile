FROM cdrx/pyinstaller-windows:python3 AS builder

WORKDIR /src
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src/ ./src/
RUN pyinstaller --onefile --console --name file_server --add-data "src/templates;templates" src/server.py
