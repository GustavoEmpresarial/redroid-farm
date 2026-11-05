"""Regression checks for device allocation and dashboard control actions."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import server


class ControlTests(unittest.TestCase):
    def request(self, path, body=None):
        handler = server.FarmHandler.__new__(server.FarmHandler)
        handler.path = path
        handler._json = Mock()
        handler._error = Mock()
        if body is None:
            handler.do_GET()
        else:
            raw = json.dumps(body).encode()
            handler.headers = {"Content-Length": str(len(raw))}
            handler.rfile = io.BytesIO(raw)
            handler.do_POST()
        return handler

    def test_powered_off_device_keeps_reserved_adb_port(self):
        listing = json.dumps({"ID": "abc123", "Names": "redroid-phone-1", "Ports": "", "State": "exited"})
        inspection = json.dumps([{"Id": "abc123-full-id", "HostConfig": {"PortBindings": {"5555/tcp": [{"HostPort": "5556"}]}}}])
        with patch.object(server, "run_cmd", side_effect=[(0, listing, ""), (0, inspection, "")]):
            devices = server.get_docker_containers()
        self.assertEqual(devices[0]["adb_port"], 5556)
        self.assertEqual(devices[0]["adb_serial"], "127.0.0.1:5556")
        self.assertFalse(devices[0]["running"])
        self.assertEqual(server.get_next_available_port(containers=devices), 5557)

    def test_defaults_do_not_reuse_names_or_ports(self):
        devices = [{"name": "redroid-phone-1", "adb_port": 5556}, {"name": "redroid-phone-3", "adb_port": 5557}]
        with patch.object(server, "get_docker_containers", return_value=devices):
            handler = self.request("/api/devices/defaults")
        handler._json.assert_called_once_with({"ok": True, "name": "redroid-phone-2", "port": 5558})

    def test_global_action_reports_partial_failure(self):
        devices = [{"name": "redroid-phone-1"}, {"name": "redroid-phone-2"}]
        with patch.object(server, "get_docker_containers", return_value=devices), patch.object(server, "run_cmd", side_effect=[(0, "one", ""), (1, "", "Docker operation failed")]) as command:
            handler = self.request("/api/devices/all/action", {"action": "stop"})
        result = handler._json.call_args.args[0]
        self.assertFalse(result["ok"])
        self.assertEqual(result["count"], 1)
        self.assertIn("redroid-phone-2", result["error"])
        self.assertEqual(handler._json.call_args.kwargs["status"], 502)
        self.assertEqual(command.call_args_list[0].args[0], ["docker", "stop", "-t", "2", "redroid-phone-1"])

    def test_start_all_reconnects_adb(self):
        devices = [{"name": "redroid-phone-1", "adb_port": 5556}]
        with patch.object(server, "get_docker_containers", return_value=devices), patch.object(server, "run_cmd", return_value=(0, "one", "")), patch.object(server, "connect_in_background") as connect:
            handler = self.request("/api/devices/all/action", {"action": "start"})
        self.assertTrue(handler._json.call_args.args[0]["ok"])
        connect.assert_called_once_with(5556)

    def test_create_rejects_reserved_port_before_docker_run(self):
        with patch.object(server, "get_docker_containers", return_value=[{"name": "redroid-phone-1", "adb_port": 5556}]), patch.object(server, "run_cmd") as command:
            handler = self.request("/api/devices/create", {"name": "redroid-phone-2", "port": 5556})
        self.assertEqual(handler._error.call_args.args[1], 409)
        self.assertIn("powered-off", handler._error.call_args.args[0])
        command.assert_not_called()

    def test_create_rejects_duplicate_name_and_invalid_numbers(self):
        with patch.object(server, "get_docker_containers", return_value=[{"name": "redroid-phone-1", "adb_port": 5556}]), patch.object(server, "run_cmd") as command:
            duplicate = self.request("/api/devices/create", {"name": "redroid-phone-1"})
            invalid = self.request("/api/devices/create", {"name": "redroid-phone-2", "port": "invalid"})
        self.assertEqual(duplicate._error.call_args.args[1], 409)
        self.assertIn("whole numbers", invalid._error.call_args.args[0])
        command.assert_not_called()

    def test_create_uses_selected_resolution_and_surfaces_docker_errors(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(server, "DATA_DIR", Path(directory)), patch.object(server, "get_docker_containers", return_value=[]), patch.object(server.Path, "exists", return_value=True), patch.object(server, "connect_in_background") as connect, patch.object(server, "run_cmd", return_value=(0, "new-container-id", "")) as command:
            handler = self.request("/api/devices/create", {"name": "redroid-test", "port": 5559, "width": 540, "height": 960})
            self.assertTrue(handler._json.call_args.args[0]["ok"])
            self.assertIn("androidboot.redroid_width=540", command.call_args.args[0])
            self.assertIn("androidboot.redroid_height=960", command.call_args.args[0])
            connect.assert_called_once_with(5559)
            command.return_value = (1, "", "Port allocation failed")
            failed = self.request("/api/devices/create", {"name": "redroid-test-error", "port": 5559})
            self.assertIn("Port allocation failed", failed._error.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
