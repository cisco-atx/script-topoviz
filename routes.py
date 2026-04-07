import os
import json
import base64
import datetime
from flask import request, render_template_string

from .workers import run_topology

class TopovizScript:

    meta = {
        "name": "Topoviz",
        "version": "1.0.0",
        "description": "Discover and visualize network topology from a list of devices",
        "icon": "polyline"
    }

    url_rules = [
        {
            "rule": "/save_png",
            "endpoint": "save_png",
            "view_func": "save_png",
            "methods": ["POST"],
            "is_global": True
        },
        {
            "rule": "/save_json",
            "endpoint": "save_json",
            "view_func": "save_json",
            "methods": ["POST"]
        },
        {
            "rule": "/load_json",
            "endpoint": "load_json",
            "view_func": "load_json",
            "methods": ["POST"],
            "is_global": True
        },
        {
            "rule": "/list_json",
            "endpoint": "list_json",
            "view_func": "list_json",
            "methods": ["GET"],
            "is_global": True
        }
    ]

    def __init__(self, ctx):
        self.ctx = ctx

    @classmethod
    def input(self):
        input_template = os.path.join(
            os.path.dirname(__file__),
            "templates",
            "input.html"
        )

        static_folder = os.path.join(os.path.dirname(__file__), "static")

        return render_template_string(open(input_template).read(), static_folder=static_folder)

    def run(self, inputs):

        devices_raw = inputs.get("devices", "")
        devices = [d.strip() for d in devices_raw.split(",") if d.strip()]

        if not devices:
            self.ctx.error("No devices provided")
            return

        data = run_topology(devices=devices,ctx=self.ctx )

        filename = f"Topoviz_{datetime.datetime.now().strftime('%Y-%m-%d_%H.%M')}.json"
        with open(os.path.join(self.ctx.output_dir, filename), "w") as f:
            json.dump(data, f, indent=4)

        self.ctx.set_html("topologyData", json.dumps(data))

        self.ctx.log("Topology discovery completed")

    def list_json(self):
        files = [
            f for f in os.listdir(self.ctx.output_dir)
            if f.endswith(".json")
        ]
        return files

    def load_json(self):
        data = request.get_json()
        filename = data.get("filename")

        if not filename:
            return {"nodes": [], "edges": []}

        path = os.path.join(self.ctx.output_dir, filename)

        if not os.path.exists(path):
            return {"nodes": [], "edges": []}

        with open(path) as f:
            return json.load(f)

    def save_json(self):
        data = request.get_json()
        filename = f"Topoviz_{datetime.datetime.now().strftime('%Y-%m-%d_%H.%M')}.json"
        self.ctx.save_file(filename, json.dumps(data, indent=4).encode())

        return {"status": "saved"}

    def save_png(self):
        data = request.get_json()
        image_data = data.get("image")

        if not image_data:
            return {"status": "error", "message": "No image provided"}

        header, encoded = image_data.split(",", 1)
        image_bytes = base64.b64decode(encoded)
        filename = f"Topoviz_{datetime.datetime.now().strftime('%Y-%m-%d_%H.%M')}.png"
        self.ctx.save_file(filename, image_bytes)
        return {"status": "saved"}