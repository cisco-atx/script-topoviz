"""Topoviz routes module.

Provides Flask route handlers and script logic for discovering and
visualizing network topology. Handles JSON/PNG persistence and
interaction with the topology worker.

Path: routes.py
"""

import base64
import datetime
import json
import os

from flask import request, render_template_string

from .workers import run_topology


class TopovizScript:
    """Topoviz script handler for topology discovery and file operations."""

    meta = {
        "name": "Topoviz",
        "version": "1.0.0",
        "description": (
            "Discover and visualize network topology from a list of devices"
        ),
        "icon": "polyline",
    }

    url_rules = [
        {
            "rule": "/save_png",
            "endpoint": "save_png",
            "view_func": "save_png",
            "methods": ["POST"],
            "is_global": True,
        },
        {
            "rule": "/save_json",
            "endpoint": "save_json",
            "view_func": "save_json",
            "methods": ["POST"],
        },
        {
            "rule": "/load_json",
            "endpoint": "load_json",
            "view_func": "load_json",
            "methods": ["POST"],
            "is_global": True,
        },
        {
            "rule": "/list_json",
            "endpoint": "list_json",
            "view_func": "list_json",
            "methods": ["GET"],
            "is_global": True,
        },
    ]

    def __init__(self, ctx):
        """Initialize TopovizScript with context."""
        self.ctx = ctx

    @classmethod
    def required(self):
        return ["connector"]

    @classmethod
    def input(self):
        """Render input HTML template."""
        input_template = os.path.join(
            os.path.dirname(__file__), "templates", "input.html"
        )
        static_folder = os.path.join(
            os.path.dirname(__file__), "static"
        )

        with open(input_template, encoding="utf-8") as file:
            template_content = file.read()

        return render_template_string(
            template_content, static_folder=static_folder
        )

    def run(self, inputs):
        """Execute topology discovery and save results."""
        devices_raw = inputs.get("devices", "")
        devices = [d.strip() for d in devices_raw.split(",") if d.strip()]

        if not devices:
            self.ctx.error("No devices provided")
            return

        data = run_topology(devices=devices, ctx=self.ctx)

        filename = (
            f"Topoviz_"
            f"{datetime.datetime.now().strftime('%Y-%m-%d_%H.%M')}.json"
        )
        file_path = os.path.join(self.ctx.output_dir, filename)

        try:
            with open(file_path, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=4)
        except Exception:
            raise

        self.ctx.set_html("topologyData", json.dumps(data))
        self.ctx.log("Topology discovery completed")

    def list_json(self):
        """List available JSON topology files."""
        try:
            files = [
                f
                for f in os.listdir(self.ctx.output_dir)
                if f.endswith(".json")
            ]
            return files
        except Exception:
            return []

    def load_json(self):
        """Load a JSON topology file."""
        data = request.get_json()
        filename = data.get("filename")

        if not filename:
            return {"nodes": [], "edges": []}

        path = os.path.join(self.ctx.output_dir, filename)

        if not os.path.exists(path):
            return {"nodes": [], "edges": []}

        try:
            with open(path, encoding="utf-8") as file:
                return json.load(file)
        except Exception:
            return {"nodes": [], "edges": []}

    def save_json(self):
        """Save topology data as a JSON file."""
        data = request.get_json()
        filename = (
            f"Topoviz_"
            f"{datetime.datetime.now().strftime('%Y-%m-%d_%H.%M')}.json"
        )

        try:
            self.ctx.save_file(
                filename,
                json.dumps(data, indent=4).encode(),
            )
        except Exception:
            return {"status": "error", "message": "Save failed"}

        return {"status": "saved"}

    def save_png(self):
        """Save topology image as a PNG file."""
        data = request.get_json()
        image_data = data.get("image")

        if not image_data:
            return {"status": "error", "message": "No image provided"}

        try:
            _, encoded = image_data.split(",", 1)
            image_bytes = base64.b64decode(encoded)
        except Exception:
            return {"status": "error", "message": "Invalid image data"}

        filename = (
            f"Topoviz_"
            f"{datetime.datetime.now().strftime('%Y-%m-%d_%H.%M')}.png"
        )

        try:
            self.ctx.save_file(filename, image_bytes)
        except Exception:
            return {"status": "error", "message": "Save failed"}

        return {"status": "saved"}
